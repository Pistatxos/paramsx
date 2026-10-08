import os
import sys
import json
import shutil
import boto3
import curses
import importlib.util
from botocore.exceptions import ClientError
from . import paramsx_config as plantilla_config
from . import __version__
from .funcions import (
    draw_header, draw_footer, show_main_menu, iniciar_estilo, show_comparison_results,
    show_environment_selection, show_message, show_parameter_selection,
    get_parameters_by_prefix, delete_parameter, export_parameters_to_file,
    compare_parameters, load_parameters, show_main_menu_selection,
    AccessDeniedError, build_full_path, etiqueta_entrada, agregar_tags_a_parametros,
    validar_tags_obligatorias, aplicar_cambios_tags, check_rds_correlacion,
    agregar_descripciones_a_parametros,
    show_report, prompt_input, indexar_parametros, indice_a_parametros,
    ficheros_cargables,
    MARCADOR_ENTORNO, slug_entrada, aplicar_case_ruta,
)
from .core.config import (
    CONFIG_PATH, PLANTILLA_PATH, CLAVES_OPCIONALES, NOMBRES_ANTIGUOS,
    config_desde_valores, validate_config, normalize_config,
)
from .core.rutas import validar_marcador


# Ejecutar el fichero de configuración del usuario y devolver el módulo resultante
def cargar_modulo_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"No se encontró el archivo de configuración en {CONFIG_PATH}")
    spec = importlib.util.spec_from_file_location("config", CONFIG_PATH)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# Cargar configuraciones desde el archivo de usuario. La terminal lo ejecuta como
# siempre; los valores por defecto los rellena core, igual que en la web.
def load_config():
    return config_desde_valores(vars(cargar_modulo_config()))


# Nombres del fichero exportado y de su backup. Los usan por igual la lectura (opción 1)
# y la carga (opción 2): si no coincidieran, la carga no encontraría lo que acaba de leer.
# Con fichero_por_ruta cada entrada tiene los suyos, así que leer una segunda ruta del
# mismo entorno no machaca la que estabas editando.
def nombres_ficheros(entrada, entorno, fichero_por_ruta):
    sufijo = f"__{slug_entrada(entrada)}" if fichero_por_ruta else ""
    base = f"parameters_{entorno}{sufijo}"
    return f"{base}.py", f"{base}_backup.py"


# Leer parámetros (y sus tags si tags_activas) de una ruta ya construida
def leer_ruta(stdscr, ssm, full_path, tags_activas, tags_obligatorias):
    """Devuelve (parametros, avisos) o (None, avisos) si no se pudo leer."""
    try:
        parameters = get_parameters_by_prefix(ssm, full_path)
    except AccessDeniedError as e:
        show_report(stdscr, "Acceso denegado", [e.mensaje], color_pair=2)
        return None, []
    except ValueError as e:
        show_message(stdscr, f"{e}", 2)
        return None, []

    avisos = agregar_descripciones_a_parametros(ssm, parameters, full_path)
    if tags_activas:
        avisos.extend(agregar_tags_a_parametros(ssm, parameters, tags_obligatorias))

    return parameters, avisos


# Feature 2: crear un parámetro nuevo con el perfil declarado en 'perfil_nuevos'
def crear_parametro(stdscr, ssm, entornos, perfil, nombre_perfil, tags_activas,
                    tags_obligatorias, obligatorias_vacias=False):
    env_choice = show_environment_selection(stdscr, entornos)
    if env_choice is None:
        return
    entorno = entornos[env_choice].lower()

    posicion = perfil.get("posicion_entorno")
    case_ruta = perfil.get("case_ruta", "ninguno")

    # 1. Ruta SIN el entorno, igual que se declara en parameter_list: el perfil se
    # encarga de colocarlo. Así la opción 4 funciona con cualquier convención.
    ayudas = {
        "inicio": "El entorno se añade delante. Ej: /common/rds/cee-dev/host -> "
                  f"/{entorno}/common/rds/cee-dev/host",
        "final": "El entorno se añade al final. Ej: /API/STA/token -> "
                 f"/API/STA/token/{entorno.upper()}",
        "mixto": f"Escribe un '{MARCADOR_ENTORNO}' donde vaya el entorno. "
                 f"Ej: /API/{MARCADOR_ENTORNO}/STA/token",
        "ninguno": "Este perfil no añade entorno: la ruta se crea tal cual la escribas.",
    }
    path = ""
    while True:
        path = prompt_input(
            stdscr,
            "Crear nuevo parámetro (1/5): ruta",
            f"Ruta del parámetro (perfil '{nombre_perfil}', sin el entorno):",
            valor=path,
            ayuda=ayudas.get(posicion, ""),
        )
        if path is None:
            return

        path = aplicar_case_ruta("/" + path.strip().strip("/"), case_ruta)

        segmentos = [s for s in path.strip("/").split("/") if s]
        if not segmentos:
            show_message(stdscr, "La ruta no puede estar vacía.", 2)
            continue

        problemas = validar_marcador(path, nombre_perfil, perfil)
        if problemas:
            show_message(stdscr, problemas[0], 2)
            continue
        break

    # La ruta real en AWS, ya con el entorno colocado por el perfil
    path_declarado = path
    path = build_full_path(path_declarado, perfil, entorno)

    if not show_report(
        stdscr, "Crear nuevo parámetro (2/5): confirmar la ruta",
        [f"Perfil:  {nombre_perfil}",
         f"Escrita:    {path_declarado}",
         f"En AWS:     {path}",
         "",
         "¿La ruta es correcta?"],
        color_pair=3, confirmar=True,
    ):
        return

    # 3. Descripción: va debajo del nombre y antes del valor, igual que en el fichero
    descripcion = prompt_input(
        stdscr,
        "Crear nuevo parámetro (3/5): descripción",
        "Descripción del parámetro (opcional):",
        valor="",
        permitir_vacio=True,
        ayuda="Para qué sirve este parámetro. Se guarda en AWS y luego se puede editar "
              "en el fichero exportado. Máximo 1024 caracteres; Enter para dejarla vacía.",
    )
    if descripcion is None:
        return
    descripcion = descripcion.strip()[:1024]

    # 4. Valor (string plano o JSON)
    valor = ""
    while True:
        valor = prompt_input(
            stdscr,
            "Crear nuevo parámetro (4/5): valor",
            f"Valor para {path}:",
            valor=valor,
            ayuda='Texto plano o JSON en una línea, ej: {"host": "x", "user": "y", "pass": "z"}',
        )
        if valor is None:
            return

        candidato = valor.strip()
        if candidato.startswith("{") or candidato.startswith("["):
            try:
                json.loads(candidato)
            except json.JSONDecodeError as e:
                show_message(stdscr, f"JSON inválido: {e}", 2)
                continue
        break

    # 5. Tags obligatorias
    tags = {}
    faltantes = []
    if tags_activas:
        if obligatorias_vacias:
            ayuda_tags = ("Las tags sostienen el control de acceso ABAC vía IAM. "
                          "Puedes dejarla vacía: si no tiene valor no se creará en AWS.")
        else:
            ayuda_tags = "Las tags sostienen el control de acceso ABAC vía IAM: son obligatorias."

        for indice, clave in enumerate(tags_obligatorias, start=1):
            predeterminado = entorno if clave == "Environment" else ""
            respuesta = prompt_input(
                stdscr,
                f"Crear nuevo parámetro (5/5): tags [{indice}/{len(tags_obligatorias)}]",
                f"Valor de la tag obligatoria '{clave}':",
                valor=predeterminado,
                permitir_vacio=obligatorias_vacias,
                ayuda=ayuda_tags,
            )
            if respuesta is None:
                return
            tags[clave] = respuesta.strip()

        faltantes = validar_tags_obligatorias(tags, tags_obligatorias)
        if faltantes and not obligatorias_vacias:
            show_report(
                stdscr,
                "Tags obligatorias incompletas",
                [f"Faltan las tags: {', '.join(faltantes)}", "No se ha creado el parámetro."],
                color_pair=2,
            )
            return

        # Las tags sin valor no se suben a AWS
        tags = {clave: valor for clave, valor in tags.items() if valor}

    # Aviso de correlación de naming en RDS (no bloquea)
    aviso_rds = check_rds_correlacion(ssm, path)

    # Resumen y confirmación
    lineas = [
        f"Ruta:        {path}",
        f"Descripción: {descripcion or '(vacía)'}",
        f"Valor:       {valor[:120]}",
        "Tipo:        SecureString",
        "",
    ]
    if tags_activas:
        lineas.append("Tags:")
        lineas.extend([f"  {clave} = {valor_tag}" for clave, valor_tag in tags.items()])
        if faltantes:
            lineas.append(
                f"  Se quedan vacías (no se crearán en AWS): {', '.join(faltantes)}"
            )
        lineas.append("")
    if aviso_rds:
        lineas.extend([aviso_rds, ""])

    if not show_report(stdscr, "Confirmar creación del parámetro", lineas, color_pair=3,
                       confirmar=True):
        show_message(stdscr, "Creación cancelada.", 2)
        return

    kwargs = {
        "Name": path,
        "Value": valor,
        "Type": "SecureString",
        "Overwrite": False,
    }
    if descripcion:
        kwargs["Description"] = descripcion
    if tags_activas and tags:
        kwargs["Tags"] = [{"Key": k, "Value": v} for k, v in tags.items()]

    try:
        ssm.put_parameter(**kwargs)
    except ClientError as e:
        codigo = e.response.get("Error", {}).get("Code", "")
        if codigo == "ParameterAlreadyExists":
            show_report(
                stdscr, "El parámetro ya existe",
                [f"Ya existe un parámetro en {path}.",
                 "Usa 'Leer parámetros' y edita el fichero exportado para cambiar su valor."],
                color_pair=2,
            )
            return
        if codigo == "AccessDeniedException":
            show_report(
                stdscr, "Acceso denegado",
                [f"⚠ No tienes permisos para crear {path} — pídele a un admin que te dé acceso."],
                color_pair=2,
            )
            return
        raise

    lineas_ok = [
        f"✓ Parámetro creado correctamente: {path}",
        "",
        "Aparecerá la próxima vez que leas la ruta correspondiente de tu parameter_list.",
    ]
    if aviso_rds:
        lineas_ok.extend(["", aviso_rds])
    show_report(stdscr, "Parámetro creado", lineas_ok, color_pair=3)


# Función principal
def main(stdscr, config=None):

    ## Cargando configuración
    if config is None:
        config = normalize_config(load_config())
    # Configurar boto3 con el perfil y región del usuario
    boto3.setup_default_session(profile_name=config["profile_name"])
    ssm = boto3.client("ssm", region_name=config["region_name"])

    # Colores: los de siempre (1 a 3) y los de la portada (logo, selección y firma)
    iniciar_estilo()

    environments = config['entornos']
    PARAMETER_LIST = config['parameter_list']
    PERFILES = config['perfiles']
    TAGS_ACTIVAS = config['tags_activas']
    TAGS_OBLIGATORIAS = config['tags_obligatorias']
    OBLIGATORIAS_VACIAS = config.get('obligatorias_vacias', False)
    FICHERO_POR_RUTA = config.get('fichero_por_ruta', False)
    FORZAR_SECURESTRING = config.get('forzar_securestring', True)
    PERFIL_NUEVOS = config.get('perfil_nuevos')

    # Nombre del fichero exportado: con fichero_por_ruta cada ruta tiene el suyo, así que
    # leer una segunda ruta del mismo entorno no machaca lo que estabas editando.
    while True:
        # Usar el menú con navegación por flechas
        choice_idx = show_main_menu_selection(stdscr)
        if choice_idx is None:  # Esc en el menú principal
            break
        choice = choice_idx + 1

        if choice == 1:
            # Leer parámetros
            etiquetas = [etiqueta_entrada(e) for e in PARAMETER_LIST]
            param_choice = show_parameter_selection(stdscr, etiquetas)
            if param_choice is None:  # Si se presionó Esc
                continue  # Regresar al menú principal

            selected_param = PARAMETER_LIST[param_choice]

            env_choice = show_environment_selection(stdscr, environments)
            if env_choice is None:  # Si se presionó Esc
                continue  # Regresar al menú principal

            selected_env = environments[env_choice]

            # Crear el prefijo completo según el perfil de la entrada
            full_path = build_full_path(
                selected_param["path"], PERFILES[selected_param["perfil"]], selected_env
            )
            show_message(stdscr, f"Buscando parámetros en: {full_path}...", 3)  # Mensaje inicial

            parameters, avisos = leer_ruta(stdscr, ssm, full_path, TAGS_ACTIVAS, TAGS_OBLIGATORIAS)
            if not parameters:
                continue  # Regresar al menú principal

            # Crear archivos si se encontraron parámetros
            file_name, backup_file_name = nombres_ficheros(
                selected_param, selected_env, FICHERO_POR_RUTA
            )

            if os.path.exists(file_name):
                aviso = [f"Ya existe {file_name} de una lectura anterior.",
                         "Si tenías cambios sin cargar, se van a perder."]
                if not FICHERO_POR_RUTA:
                    aviso += ["",
                              "Con 'fichero_por_ruta = True' en tu configuración cada entrada "
                              "de parameter_list usa su propio fichero y dejan de pisarse."]
                if not show_report(stdscr, "El fichero ya existe", aviso,
                                   color_pair=2, confirmar=True):
                    continue

            # Exportar parámetros al archivo principal
            export_parameters_to_file(parameters, file_name, TAGS_ACTIVAS, TAGS_OBLIGATORIAS,
                                      incluir_tipo=not FORZAR_SECURESTRING)

            # Crear un respaldo exacto del archivo principal (valores y tags)
            export_parameters_to_file(parameters, backup_file_name, TAGS_ACTIVAS, TAGS_OBLIGATORIAS,
                                      incluir_tipo=not FORZAR_SECURESTRING)

            # Confirmación de archivos creados
            lineas = [
                f"Parámetros leídos de {full_path}: {len(parameters)}",
                "",
                "Archivos creados:",
                f"- {file_name}",
                f"- {backup_file_name}",
            ]
            if TAGS_ACTIVAS:
                lineas.extend([
                    "",
                    f"Tags obligatorias a rellenar: {', '.join(TAGS_OBLIGATORIAS)}",
                ])
            if avisos:
                lineas.append("")
                lineas.extend(avisos)
            show_report(stdscr, "Parámetros exportados", lineas, color_pair=3)

        elif choice == 2:
            # Cargar parámetros desde archivo: se eligen entre los que hay de verdad en
            # el directorio, no entre las rutas de la parameter_list. Con fichero_por_ruta
            # habrá varios y el nombre ya dice de qué ruta y entorno es cada uno.
            cargables = ficheros_cargables()
            if not cargables:
                show_report(
                    stdscr, "No hay nada que cargar",
                    ["No se ha encontrado ningún fichero de parámetros con su backup "
                     "en este directorio.",
                     "",
                     "Usa antes 'Leer parámetros', o ejecuta paramsx desde la carpeta "
                     "donde tengas los ficheros exportados."],
                    color_pair=2,
                )
                continue

            fichero_choice = show_parameter_selection(
                stdscr, [n for n, _ in cargables],
                titulo="Seleccione el fichero que quiere cargar:",
            )
            if fichero_choice is None:  # Si se presionó Esc
                continue  # Regresar al menú principal

            file_name, backup_file_name = cargables[fichero_choice]

            try:
                # Cargar parámetros del archivo principal
                load_parameters(file_name)
            except SyntaxError as e:
                show_message(stdscr, f"ERROR: {e}", 2)
                continue  # Regresar al menú principal

            # Comparar los parámetros (valores y, si tags_activas, también tags)
            changes = compare_parameters(file_name, backup_file_name, stdscr, TAGS_ACTIVAS)

            if not changes:
                show_message(stdscr, "No se encontraron cambios entre los archivos.", 3)
                continue

            # Mostrar resultados de la comparación
            confirmed = show_comparison_results(stdscr, changes)

            if not confirmed:  # Si el usuario cancela
                show_message(stdscr, "Operación cancelada volvemos a menú principal.", 2)
                continue

            aplicados = []
            errores = []
            vacias = []

            for change in changes:
                param_name = change["name"]
                tipo = change["tipo"]

                if tipo in ("Nuevo", "Modificado"):
                    if TAGS_ACTIVAS:
                        faltantes = validar_tags_obligatorias(change["tags"], TAGS_OBLIGATORIAS)
                        if faltantes and not OBLIGATORIAS_VACIAS:
                            # Validación bloqueante por parámetro: sin las tags no se sube nada
                            errores.append(
                                f"✗ {param_name}: no se ha subido (ni valor ni tags). "
                                f"Faltan las tags obligatorias: {', '.join(faltantes)}."
                            )
                            continue
                        if faltantes:
                            # Permitidas vacías: se sube igual y esas tags no se crean en AWS
                            vacias.append(
                                f"· {param_name}: sin valor en {', '.join(faltantes)} "
                                "(no se crean en AWS)."
                            )

                    try:
                        if (change["value_changed"] or change.get("description_changed")
                                or change.get("type_changed")):
                            kwargs_put = {
                                "Name": param_name,
                                "Value": change["value"],
                                "Overwrite": True,
                            }
                            # El 'Type' solo es obligatorio al CREAR: al actualizar, si no
                            # se manda, AWS conserva el que tuviera el parámetro. Por eso
                            # con forzar_securestring = False se omite en las
                            # modificaciones en vez de adivinarlo.
                            if FORZAR_SECURESTRING:
                                kwargs_put["Type"] = "SecureString"
                            elif change.get("type"):
                                kwargs_put["Type"] = change["type"]
                            elif tipo == "Nuevo":
                                kwargs_put["Type"] = "SecureString"
                            # put_parameter con Overwrite reescribe la definición del
                            # parámetro: si no se manda la descripción, la que hubiera en
                            # AWS se pierde. Así que se manda siempre que el fichero la
                            # traiga, incluso cuando lo que cambió fue solo el valor.
                            if change.get("description") is not None:
                                kwargs_put["Description"] = change["description"]
                            ssm.put_parameter(**kwargs_put)
                        # Los cambios de tags se aplican en la misma pasada que el valor
                        aplicar_cambios_tags(
                            ssm, param_name, change["tags_set"], change["tags_remove"]
                        )
                    except AccessDeniedError as e:
                        errores.append(f"✗ {param_name}: {e.mensaje}")
                        continue
                    except ClientError as e:
                        if e.response.get("Error", {}).get("Code", "") == "AccessDeniedException":
                            errores.append(
                                f"✗ {param_name}: ⚠ No tienes permisos para escribir en esa ruta "
                                "— pídele a un admin que te dé acceso."
                            )
                            continue
                        raise

                    aplicados.append(change)

                elif tipo == "Eliminado":
                    # Borrar parámetros eliminados
                    try:
                        delete_parameter(ssm, param_name)
                    except AccessDeniedError as e:
                        errores.append(f"✗ {param_name}: {e.mensaje}")
                        continue
                    aplicados.append(change)

            lineas = [f"Cambios aplicados: {len(aplicados)} de {len(changes)}"]

            if vacias:
                lineas.extend(["", f"Tags obligatorias vacías ({len(vacias)}):"])
                lineas.extend(vacias)

            if errores:
                # Se conservan los ficheros para que el usuario corrija y vuelva a cargar.
                # El backup se resincroniza con lo ya aplicado para no repetir esos cambios.
                indice = indexar_parametros(load_parameters(backup_file_name))
                for change in aplicados:
                    if change["tipo"] == "Eliminado":
                        indice.pop(change["name"], None)
                    else:
                        indice[change["name"]] = {
                            "value": change["value"],
                            "tags": change["tags"],
                        }
                export_parameters_to_file(
                    indice_a_parametros(indice), backup_file_name, TAGS_ACTIVAS,
                    TAGS_OBLIGATORIAS, incluir_tipo=not FORZAR_SECURESTRING
                )

                lineas.extend(["", f"Errores ({len(errores)}):"])
                lineas.extend(errores)
                lineas.extend([
                    "",
                    f"Se conservan {file_name} y {backup_file_name}: corrige lo que falta",
                    "y vuelve a cargar el fichero para subir solo lo que quedó pendiente.",
                ])
                show_report(stdscr, "Carga parcial", lineas, color_pair=2)
            else:
                # Eliminar los archivos una vez procesados
                os.remove(file_name)
                os.remove(backup_file_name)
                lineas.extend(["", "¡Cambios aplicados y archivos eliminados!"])
                show_report(stdscr, "Carga completada", lineas, color_pair=3)

        elif choice == 3:
            # Crear backup
            OPCION_LISTADOS = "Total parámetros listados."
            OPCION_CUENTA = "Total parámetros de la cuenta."
            etiquetas = [etiqueta_entrada(e) for e in PARAMETER_LIST]
            etiquetas = etiquetas + [OPCION_LISTADOS, OPCION_CUENTA]

            param_choice = show_parameter_selection(
                stdscr, etiquetas, titulo="Seleccione qué quiere respaldar:"
            )
            if param_choice is None:  # Si se presionó Esc
                continue  # Regresar al menú principal

            if etiquetas[param_choice] == OPCION_LISTADOS:
                # Crear backup de todos los parámetros listados
                all_parameters = []
                avisos_totales = []
                for entrada in PARAMETER_LIST:
                    for env in environments:
                        full_path = build_full_path(
                            entrada["path"], PERFILES[entrada["perfil"]], env
                        )
                        try:
                            # Obtener parámetros desde AWS SSM
                            parameters = get_parameters_by_prefix(ssm, full_path)
                        except AccessDeniedError as e:
                            avisos_totales.append(e.mensaje)
                            continue
                        except ValueError:
                            # Ruta sin parámetros para ese entorno: se ignora en el backup total
                            continue

                        avisos_totales.extend(
                            agregar_descripciones_a_parametros(ssm, parameters, full_path)
                        )
                        if TAGS_ACTIVAS:
                            avisos_totales.extend(
                                agregar_tags_a_parametros(ssm, parameters, TAGS_OBLIGATORIAS)
                            )
                        all_parameters.extend(parameters)

                # Crear archivo de backup total listado
                backup_file_name = "total_listed_parameters_backup.py"
                export_parameters_to_file(
                    all_parameters, backup_file_name, TAGS_ACTIVAS, TAGS_OBLIGATORIAS,
                    incluir_tipo=not FORZAR_SECURESTRING
                )

                # Confirmación de backup creado
                lineas = [
                    f"Backup total listado creado: {backup_file_name}",
                    f"Parámetros incluidos: {len(all_parameters)}",
                ]
                if avisos_totales:
                    lineas.append("")
                    lineas.extend(avisos_totales)
                show_report(stdscr, "Backup total listado", lineas, color_pair=3)

            elif etiquetas[param_choice] == OPCION_CUENTA:
                # Obtener todos los parámetros desde AWS SSM
                parameters, avisos = leer_ruta(stdscr, ssm, "/", TAGS_ACTIVAS, TAGS_OBLIGATORIAS)
                if not parameters:
                    continue  # Regresar al menú principal

                # Crear archivo de backup de todos los parámetros
                backup_file_name = "all_parameters_backup.py"
                export_parameters_to_file(
                    parameters, backup_file_name, TAGS_ACTIVAS, TAGS_OBLIGATORIAS,
                    incluir_tipo=not FORZAR_SECURESTRING
                )
                lineas = [
                    f"Backup de todos los parámetros creado: {backup_file_name}",
                    f"Parámetros incluidos: {len(parameters)}",
                ]
                if avisos:
                    lineas.append("")
                    lineas.extend(avisos)
                show_report(stdscr, "Backup de la cuenta", lineas, color_pair=3)

            else:
                # Backup normal para un prefijo específico
                selected_param = PARAMETER_LIST[param_choice]

                env_choice = show_environment_selection(stdscr, environments)
                if env_choice is None:  # Si se presionó Esc
                    continue  # Regresar al menú principal

                selected_env = environments[env_choice]

                # Crear el prefijo completo según el perfil de la entrada
                full_path = build_full_path(
                    selected_param["path"], PERFILES[selected_param["perfil"]], selected_env
                )

                parameters, avisos = leer_ruta(stdscr, ssm, full_path, TAGS_ACTIVAS, TAGS_OBLIGATORIAS)
                if not parameters:
                    continue  # Regresar al menú principal

                # Crear archivo de backup con nombre claro
                backup_file_name = f"{slug_entrada(selected_param)}_{selected_env}_backup.py"
                export_parameters_to_file(
                    parameters, backup_file_name, TAGS_ACTIVAS, TAGS_OBLIGATORIAS,
                    incluir_tipo=not FORZAR_SECURESTRING
                )

                # Confirmación de backup creado
                lineas = [
                    f"Backup creado: {backup_file_name}",
                    f"Ruta leída: {full_path}",
                    f"Parámetros incluidos: {len(parameters)}",
                ]
                if avisos:
                    lineas.append("")
                    lineas.extend(avisos)
                show_report(stdscr, "Backup creado", lineas, color_pair=3)

        elif choice == 4:
            # Crear nuevo parámetro con el perfil declarado en 'perfil_nuevos'
            crear_parametro(
                stdscr, ssm, environments, PERFILES[PERFIL_NUEVOS], PERFIL_NUEVOS,
                TAGS_ACTIVAS, TAGS_OBLIGATORIAS, OBLIGATORIAS_VACIAS
            )

        else:
            show_message(stdscr, "Opción inválida. Inténtalo de nuevo.", 2)


# Función para crear la configuración inicial
def create_config(escribir_ejemplo=False):
    config_dir = os.path.expanduser("~/.xsoft")
    os.makedirs(config_dir, exist_ok=True)

    config_file = os.path.join(config_dir, "paramsx_config.py")
    if not os.path.exists(config_file):
        # Se copia la plantilla del paquete para no duplicar el formato en dos sitios
        shutil.copyfile(PLANTILLA_PATH, config_file)
        print(f"Archivo de configuración creado en {config_file}.")
        print("Ábrelo y ajústalo con tus valores: viene con cada opción comentada.")
        return

    # Con configuración ya hecha no se toca NADA: solo se revisa y se informa.
    print(f"Ya tienes configuración en {config_file}, no se sobrescribe.")
    print()
    revisar_config(config_file)

    ejemplo_file = os.path.join(config_dir, "paramsx_config.ejemplo.py")
    if escribir_ejemplo:
        shutil.copyfile(PLANTILLA_PATH, ejemplo_file)
        print(f"\nPlantilla de esta versión escrita en {ejemplo_file}.")
        print("Es solo una referencia para comparar: ParamsX no la lee.")
    else:
        print("\nPara dejar la plantilla de esta versión al lado de la tuya y comparar:")
        print("  paramsx configure --ejemplo")


# Valor por defecto en una línea: el repr de 'perfiles' o de las tags ocupa media pantalla
def resumir_valor(valor):
    if isinstance(valor, dict):
        return f"{len(valor)} perfiles ({', '.join(valor)})"
    if isinstance(valor, (list, tuple)):
        elementos = ", ".join(str(v) for v in valor)
        if len(elementos) > 50:
            elementos = ", ".join(str(v) for v in list(valor)[:3]) + ", ..."
        return f"{len(valor)} elementos ({elementos})"
    return repr(valor)


# Revisar una configuración existente sin modificarla: qué opciones nuevas le faltan
# (que no son un error, se usa el valor por defecto) y qué está mal de verdad.
def revisar_config(config_file):
    try:
        modulo = cargar_modulo_config()
    except Exception as e:
        print(f"No se ha podido leer: {e}")
        return

    faltan = [clave for clave in CLAVES_OPCIONALES if not hasattr(modulo, clave)]

    # Los nombres antiguos siguen funcionando, así que lo que cubren no "falta":
    # solo se avisa de que hay una forma más clara de escribirlo.
    antiguos = [(v, n) for v, n in NOMBRES_ANTIGUOS.items() if hasattr(modulo, v)]
    lista = getattr(modulo, "configuraciones", {})
    lista = lista.get("parameter_list", []) if isinstance(lista, dict) else []
    con_convencion = [
        e for e in lista
        if isinstance(e, dict) and "perfil" not in e and "convencion" in e
    ]

    if antiguos or con_convencion:
        print("Nombres antiguos que sigues usando. Funcionan, pero el nuevo se entiende mejor:")
        for viejo, nuevo in antiguos:
            if nuevo in faltan:
                faltan.remove(nuevo)
            print(f"  {viejo:20} -> {nuevo}")
        if con_convencion:
            print(f"  {'convencion':20} -> perfil "
                  f"(en {len(con_convencion)} entrada(s) de parameter_list)")
        print()

    if faltan:
        print("Opciones que no tienes y que ParamsX rellena con el valor por defecto:")
        for clave in faltan:
            print(f"  {clave:20} -> {resumir_valor(getattr(plantilla_config, clave))}")
        print("Añádelas solo si quieres cambiarlas; sin ellas todo sigue funcionando igual.")
    else:
        print("No te falta ninguna opción de esta versión.")

    try:
        # Validar SIN normalizar: normalize_config pasa 'entornos' a minúscula y se
        # perdería el aviso de que están en mayúscula en el fichero del usuario.
        errores, avisos = validate_config(load_config())
    except Exception as e:
        print(f"\nNo se ha podido validar: {e}")
        return

    if avisos:
        print()
        for aviso in avisos:
            print(aviso)
    if errores:
        print("\nErrores que hay que corregir:\n")
        for error in errores:
            print(f"{error}\n")
    else:
        print("\nLa configuración es válida.")


# Versión instalada del paquete; si se ejecuta desde el código fuente, la del módulo
def version_actual():
    try:
        from importlib.metadata import version, PackageNotFoundError
        try:
            return version("paramsx")
        except PackageNotFoundError:
            return f"{__version__} (desde el código fuente, sin instalar)"
    except ImportError:
        return __version__

# Mostrar ayuda
def show_help():
    # Texto plano, no f-string: lleva llaves literales de los dicts de ejemplo
    help_text = """
ParamsX __VERSION__ - Gestión de Parámetros de AWS SSM

Comandos disponibles:
  paramsx                   Pregunta si quieres la versión web o la de terminal.
  paramsx --web             Abre la versión web en el navegador.
  paramsx --tui             Abre la versión de terminal (requiere configuración previa).
  paramsx configure         Crea ~/.xsoft/paramsx_config.py la primera vez. Si ya lo tienes,
                            NO lo toca: revisa qué opciones nuevas te faltan y si es válido.
  paramsx configure --ejemplo   Además deja la plantilla de esta versión al lado, como
                            paramsx_config.ejemplo.py, para comparar sin tocar la tuya.
  paramsx --version         Muestra la versión instalada.
  paramsx --help            Muestra esta ayuda.

Opciones del menú:
  1. Leer parámetros              Exporta a un fichero editable los parámetros de una ruta.
  2. Cargar parámetros            Elige uno de los ficheros exportados que tengas en el
                                  directorio, compara y aplica los cambios en AWS.
  3. Crear Backup de parámetros   Respalda una ruta, la lista completa o toda la cuenta.
  4. Crear nuevo parámetro        Crea un parámetro nuevo con el perfil de 'perfil_nuevos'.

Configuración (~/.xsoft/paramsx_config.py). El fichero trae comentada cada opción:
  profile_name      Perfil de ~/.aws/credentials.
  region_name       Región de AWS.
  entornos          Lista de entornos, SIEMPRE en minúscula: ['dev', 'pre', 'prod'].
                    Cada perfil decide cómo se escriben en la ruta.
  perfiles          Cómo se construye la ruta real en AWS. Los
                    nombres los eliges tú y combinas estos tres campos:
                      posicion_entorno  'inicio'  /rds       -> /dev/rds
                                        'final'   /API/STA   -> /API/STA/DEV
                                        'mixto'   /API/*/STA -> /API/DEV/STA
                                        'ninguno' /api/auth  -> /api/auth
                      case_entorno      'lower' | 'upper' | 'capitalize'
                      case_ruta         'lower' | 'upper' | 'capitalize' | 'ninguno'
                                        (solo al crear parámetros, opción 4)
  parameter_list    Lista de dicts {"path": "/rds", "perfil": "<nombre de un perfil>"}.
  perfil_nuevos     Perfil que usan los parámetros creados con la opción 4.
  fichero_por_ruta  True -> el fichero exportado lleva entorno, ruta y perfil en el
                    nombre, para que leer otra ruta del mismo entorno no machaque la
                    anterior: parameters_dev__API_STA__max.py
  tags_activas      True para gestionar las tags en el fichero exportado y validarlas.
                    (antes se llamaba 'abac'; ese nombre se sigue aceptando)
  tags_obligatorias Tags exigidas en cada parámetro cuando tags_activas = True.
  obligatorias_vacias  False -> no se sube un parámetro al que le falte alguna tag.
                       True  -> se permite dejarlas vacías; las tags sin valor
                                no se crean en AWS.

Si necesitas más ayuda puedes leer el readme en GitHub o en Pypi:
- https://github.com/Pistatxos/paramsx
- https://pypi.org/project/paramsx/

"""
    print(help_text.replace("__VERSION__", version_actual()))

MENSAJE_SIN_FLASK = "La versión web necesita Flask y no está instalado: reinstala paramsx o haz pip install flask"


# Menú de arranque: web o terminal. Devuelve "web", "tui" o None (salir).
# En una terminal se elige con ← →, Intro o el número; sin terminal (tubería), con input().
def elegir_modo():
    from .web import flask_disponible
    hay_web = flask_disponible()
    elegida = "1" if hay_web else "2"
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return _elegir_modo_texto(hay_web, elegida)

    aviso = ""
    try:
        while True:
            _limpiar()
            print(portada(hay_web, elegida))
            print("  " + _color("← → para elegir · Intro para abrir · q para salir", "tenue"))
            if aviso:
                print("  " + _color(aviso, "acento"))
            tecla = _leer_tecla()
            aviso = ""
            if tecla in ("izquierda", "arriba"):
                elegida = "1"
            elif tecla in ("derecha", "abajo"):
                elegida = "2"
            elif tecla in ("1", "2"):
                elegida = tecla
                tecla = "intro"
            elif tecla in ("q", "Q", "esc"):
                _limpiar()
                return None
            if tecla == "intro":
                if elegida == "1" and not hay_web:
                    aviso = MENSAJE_SIN_FLASK + ". Mientras, puedes usar la terminal."
                    continue
                _limpiar()
                return "web" if elegida == "1" else "tui"
    except KeyboardInterrupt:
        _limpiar()
        return None


def _elegir_modo_texto(hay_web, defecto):
    print(portada(hay_web, defecto))
    while True:
        try:
            opcion = input(f"  › Elige 1 o 2 [Intro = {defecto}]: ").strip() or defecto
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if opcion == "1" and hay_web:
            return "web"
        if opcion == "1":
            print("  " + MENSAJE_SIN_FLASK + ". Mientras, puedes usar la terminal (2).")
            continue
        if opcion == "2":
            return "tui"
        if opcion.lower() in ("q", "salir"):
            return None


def _limpiar():
    print("\033[H\033[2J\033[3J", end="", flush=True)


# Una pulsación sin esperar a Intro: "izquierda", "derecha", "arriba", "abajo", "intro",
# "esc" o el carácter tal cual. Ctrl+C sigue lanzando KeyboardInterrupt.
def _leer_tecla():
    if os.name == "nt":
        import msvcrt
        c = msvcrt.getwch()
        if c in ("\x00", "\xe0"):
            return {"K": "izquierda", "M": "derecha", "H": "arriba", "P": "abajo"}.get(msvcrt.getwch(), "")
        if c == "\x03":
            raise KeyboardInterrupt
        return {"\r": "intro", "\x1b": "esc"}.get(c, c)

    import select
    import termios
    import tty
    fd = sys.stdin.fileno()
    antes = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        c = os.read(fd, 1).decode(errors="ignore")
        if c == "\x1b":
            # Una flecha llega como ESC [ C; un Esc suelto no trae nada detrás
            if not select.select([fd], [], [], 0.05)[0]:
                return "esc"
            resto = os.read(fd, 2).decode(errors="ignore")
            return {"[D": "izquierda", "[C": "derecha", "[A": "arriba", "[B": "abajo",
                    "OD": "izquierda", "OC": "derecha", "OA": "arriba", "OB": "abajo"}.get(resto, "")
        return {"\n": "intro", "\r": "intro"}.get(c, c)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, antes)


# Colores ANSI solo si la salida es una terminal y no se ha pedido NO_COLOR
from .text import DEGRADADO_256, ACENTO_256, TENUE_256, FOOTER_TEXT  # noqa: E402
_COLORES = {"acento": f"38;5;{ACENTO_256}", "tenue": f"38;5;{TENUE_256}", "negrita": "1"}
_DEGRADADO = tuple(f"38;5;{c}" for c in DEGRADADO_256)


def _hay_color():
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"


def _color(texto, estilo):
    if not _hay_color():
        return texto
    return f"\033[{_COLORES.get(estilo, estilo)}m{texto}\033[0m"


# Las dos tarjetas, lado a lado. La elegida va en color; la web, apagada si
# no está Flask. Se componen en texto plano y luego se colorean línea a línea, para que
# los códigos ANSI no descuadren el ancho.
def _tarjetas(hay_web, defecto):
    ancho = 30
    web = [
        "1 · WEB",
        "",
        "┌──────────────────────┐",
        "│ ● ● ●   127.0.0.1    │",
        "│ ▤▤▤▤  ▤▤▤▤▤▤  ▤▤▤    │",
        "│ ▤▤▤▤▤▤▤  ▤▤▤▤  ▤▤    │",
        "└──────────────────────┘",
        "En el navegador" if hay_web else "Falta Flask: pip install flask",
    ]
    tui = [
        "2 · TERMINAL",
        "",
        "┌──────────────────────┐",
        "│ $ paramsx            │",
        "│ > 1. Leer parámetros │",
        "│   2. Cargar          │",
        "└──────────────────────┘",
        "El menú de siempre",
    ]

    def caja(lineas, opcion):
        estilo = "acento" if opcion == defecto else "tenue"
        if opcion == "1" and not hay_web:
            estilo = "tenue"
        borde = (lambda t: _color(t, estilo))
        filas = [borde("╭" + "─" * ancho + "╮")]
        for i, linea in enumerate(lineas):
            texto = f"  {linea}".ljust(ancho)
            if i == 0:
                texto = _color(texto, "negrita") if estilo == "acento" else texto
            elif i == len(lineas) - 1:
                texto = _color(texto, "tenue")
            filas.append(borde("│") + texto + borde("│"))
        filas.append(borde("╰" + "─" * ancho + "╯"))
        return filas

    return [f"  {a}  {b}" for a, b in zip(caja(web, "1"), caja(tui, "2"))]


def portada(hay_web, defecto):
    from .text import HEADER_ASCII
    columnas = shutil.get_terminal_size((80, 24)).columns
    if columnas < 70:
        lineas = [f"ParamsX {__version__} · {FOOTER_TEXT}",
                  "  1. Web       " + ("(en el navegador)" if hay_web else "(falta Flask: pip install flask)"),
                  "  2. Terminal  (el menú de siempre)"]
        return "\n".join(lineas)

    logo = [l for l in HEADER_ASCII.split("\n") if l.strip()]
    lineas = [""]
    for i, linea in enumerate(logo):
        lineas.append("  " + _color(linea, _DEGRADADO[i % len(_DEGRADADO)]))
    lineas.append("  " + _color(f"SSM Parameter Store · v{__version__} · ", "tenue") + _color(FOOTER_TEXT, "acento"))
    lineas.append("")
    lineas.extend(_tarjetas(hay_web, defecto))
    lineas.append("")
    return "\n".join(lineas)


def arrancar_web():
    from .web import flask_disponible
    if not flask_disponible():
        print(MENSAJE_SIN_FLASK)
        return
    from .web.app import arrancar
    arrancar(abrir_navegador="--sin-navegador" not in sys.argv[1:])


# Entry point
def entry_point():
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command in ["configure", "config", "configurar"]:
            create_config(escribir_ejemplo="--ejemplo" in sys.argv[2:])
            return
        elif command in ["--help", "-h"]:
            show_help()
            return
        elif command in ["--version", "-v", "version"]:
            print(f"paramsx {version_actual()}")
            return

    argumentos = sys.argv[1:]
    if "--web" in argumentos:
        modo = "web"
    elif "--tui" in argumentos:
        modo = "tui"
    else:
        modo = elegir_modo()
    if modo is None:
        return
    if modo == "web":
        # La web no necesita la configuración previa: se hace desde Ajustes
        arrancar_web()
        return

    # Verificar que exista el archivo de configuración
    if not os.path.exists(CONFIG_PATH):
        print("ParamsX todavía no está configurado.")
        print(f"No existe {CONFIG_PATH}.")
        print()
        print("Ejecuta 'paramsx configure': te crea el fichero con cada opción comentada")
        print("para que lo ajustes con tu perfil de AWS, tus entornos y tus rutas.")
        return

    # Validar la configuración antes de entrar en la interfaz curses
    try:
        config = load_config()
    except Exception as e:
        print(f"Error al leer {CONFIG_PATH}: {e}")
        return

    errores, avisos = validate_config(config)
    for aviso in avisos:
        print(aviso)
    if errores:
        print(f"\nErrores en {CONFIG_PATH}:\n")
        for error in errores:
            print(f"{error}\n")
        return

    config = normalize_config(config)

    # Ejecutar el programa principal
    import curses
    from .main import main
    curses.wrapper(lambda stdscr: main(stdscr, config))


if __name__ == "__main__":
    curses.wrapper(main)
