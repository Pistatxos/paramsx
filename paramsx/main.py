import os
import sys
import json
import shutil
import boto3
import curses
import importlib.util
from botocore.exceptions import ClientError
from . import paramsx_config as plantilla_config
from .funcions import (
    draw_header, draw_footer, show_main_menu, show_comparison_results,
    show_environment_selection, show_message, show_parameter_selection,
    get_parameters_by_prefix, delete_parameter, export_parameters_to_file,
    compare_parameters, load_parameters, show_main_menu_selection,
    AccessDeniedError, build_full_path, etiqueta_entrada, agregar_tags_a_parametros,
    validar_tags_obligatorias, aplicar_cambios_tags, check_rds_correlacion,
    show_report, prompt_input, indexar_parametros, indice_a_parametros,
    ficheros_cargables,
    POSICIONES_ENTORNO, CASES_ENTORNO, CASES_RUTA, MARCADOR_ENTORNO, slug_entrada,
    aplicar_case_ruta,
)


# Ruta de la configuración personalizada
CONFIG_PATH = os.path.expanduser("~/.xsoft/paramsx_config.py")

# Ruta de la plantilla que se copia con 'paramsx configure'
PLANTILLA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paramsx_config.py")

MENSAJE_MIGRACION = """BREAKING CHANGE en la configuración de ParamsX
------------------------------------------------
'parameter_list' ya no es una lista de strings: ahora cada entrada es un diccionario
que declara qué perfil de naming usa. Edita a mano ~/.xsoft/paramsx_config.py:

    "entornos": ['dev', 'pre', 'prod'],   # SIEMPRE en minúscula
    "parameter_list": [
        {"path": "/common",   "convencion": "min"},   # /common   + dev -> /dev/common
        {"path": "/rds",      "convencion": "min"},   # /rds      + dev -> /dev/rds
        {"path": "/EMAIL",    "convencion": "max"},   # /EMAIL    + dev -> /EMAIL/DEV
        {"path": "/API/STA",  "convencion": "max"},   # /API/STA  + dev -> /API/STA/DEV
    ]

Los perfiles se definen en el diccionario 'naming' del mismo fichero, con la posición
y el case del entorno. 'min' y 'max' vienen predefinidos en la plantilla.

Ya no existe 'entornos_old': el entorno se escribe a partir de la lista 'entornos',
que va siempre en minúscula, aplicándole el 'case_entorno' del perfil."""


# Cargar configuraciones desde el archivo de usuario
def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"No se encontró el archivo de configuración en {CONFIG_PATH}")
    spec = importlib.util.spec_from_file_location("config", CONFIG_PATH)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    config = dict(modulo.configuraciones)
    # Todo lo que va fuera de 'configuraciones' es opcional en el fichero del usuario:
    # si no está, se usa el valor de la plantilla que trae el paquete.
    config["naming"] = dict(getattr(modulo, "naming", plantilla_config.naming))
    # 'abac' es el nombre antiguo (2.0/2.1) de 'tags_activas': se sigue aceptando.
    config["tags_activas"] = bool(
        getattr(modulo, "tags_activas", getattr(modulo, "abac", plantilla_config.tags_activas))
    )
    config["obligatorias_vacias"] = bool(
        getattr(modulo, "obligatorias_vacias", plantilla_config.obligatorias_vacias)
    )
    config["tags_obligatorias"] = list(
        getattr(modulo, "tags_obligatorias", plantilla_config.tags_obligatorias)
    )
    config["fichero_por_ruta"] = bool(
        getattr(modulo, "fichero_por_ruta", plantilla_config.fichero_por_ruta)
    )
    # Si no se declara, los parámetros nuevos usan el primer perfil definido
    primer_perfil = next(iter(config["naming"]), None)
    config["convencion_nuevos"] = getattr(modulo, "convencion_nuevos", None) or primer_perfil
    return config


# Validar la configuración del usuario. Devuelve (errores, avisos).
def validate_config(config):
    errores = []
    avisos = []

    for clave in ("profile_name", "region_name", "entornos", "parameter_list"):
        if clave not in config:
            errores.append(f"Falta la clave '{clave}' en configuraciones.")

    entornos = config.get("entornos")
    if isinstance(entornos, (list, tuple)) and entornos:
        if any(str(e) != str(e).lower() for e in entornos):
            avisos.append(
                "Aviso: 'entornos' debe escribirse en minúscula ('dev', 'pre', 'prod'). "
                "Se normalizará automáticamente, pero actualiza tu configuración."
            )
    elif "entornos" in config:
        errores.append("'entornos' debe ser una lista no vacía de entornos en minúscula.")

    naming = config.get("naming")
    if not isinstance(naming, dict) or not naming:
        errores.append(
            "'naming' debe ser un diccionario con al menos un perfil "
            "(ver la plantilla en el propio fichero de configuración)."
        )
        naming = {}
    else:
        errores.extend(validar_naming(naming))

    convencion_nuevos = config.get("convencion_nuevos")
    if naming and convencion_nuevos not in naming:
        errores.append(
            f"'convencion_nuevos' apunta a un perfil que no existe: {convencion_nuevos!r}. "
            f"Perfiles definidos en 'naming': {', '.join(sorted(naming))}."
        )

    parameter_list = config.get("parameter_list")
    if not isinstance(parameter_list, (list, tuple)) or not parameter_list:
        if "parameter_list" in config:
            errores.append("'parameter_list' debe ser una lista no vacía.")
        return errores, avisos

    if any(isinstance(entrada, str) for entrada in parameter_list):
        errores.append(MENSAJE_MIGRACION)
        return errores, avisos

    for entrada in parameter_list:
        if not isinstance(entrada, dict):
            errores.append(f"Entrada inválida en parameter_list: {entrada!r}")
            continue
        path = entrada.get("path")
        convencion = entrada.get("convencion")
        if not isinstance(path, str) or not path.strip("/"):
            errores.append(f"'path' inválido o vacío en parameter_list: {entrada!r}")
            continue
        if not path.startswith("/"):
            errores.append(f"El 'path' debe empezar por '/': {path!r}")
        if convencion not in naming:
            errores.append(
                f"'convencion' inválida en {path!r}: {convencion!r}. "
                f"Perfiles definidos en 'naming': {', '.join(sorted(naming)) or '(ninguno)'}."
            )
            continue
        errores.extend(validar_marcador(path, convencion, naming[convencion]))

    # Dos entradas que resuelvan a la misma ruta no rompen nada, pero duplican trabajo
    # y confunden en el menú, así que se avisa.
    vistas = {}
    entornos_muestra = config.get("entornos") or ["dev"]
    for entrada in parameter_list:
        perfil = naming.get(entrada.get("convencion")) if isinstance(entrada, dict) else None
        if not isinstance(perfil, dict):
            continue
        try:
            resuelta = build_full_path(entrada["path"], perfil, str(entornos_muestra[0]).lower())
        except ValueError:
            continue
        anterior = vistas.get(resuelta)
        if anterior and anterior != entrada["path"]:
            avisos.append(
                f"Aviso: '{anterior}' y '{entrada['path']}' resuelven a la misma ruta "
                f"({resuelta}). Aparecerán dos veces en el menú."
            )
        vistas.setdefault(resuelta, entrada["path"])

    return errores, avisos


# Validar los perfiles de naming. Devuelve la lista de errores.
def validar_naming(naming):
    errores = []
    for nombre, perfil in naming.items():
        if not isinstance(perfil, dict):
            errores.append(f"El perfil de naming {nombre!r} debe ser un diccionario.")
            continue

        posicion = perfil.get("posicion_entorno")
        if posicion not in POSICIONES_ENTORNO:
            errores.append(
                f"'posicion_entorno' inválida en el perfil {nombre!r}: {posicion!r}. "
                f"Usa una de: {', '.join(POSICIONES_ENTORNO)}."
            )

        case_entorno = perfil.get("case_entorno", "lower")
        if case_entorno not in CASES_ENTORNO:
            errores.append(
                f"'case_entorno' inválido en el perfil {nombre!r}: {case_entorno!r}. "
                f"Usa uno de: {', '.join(CASES_ENTORNO)}."
            )

        case_ruta = perfil.get("case_ruta", "ninguno")
        if case_ruta not in CASES_RUTA:
            errores.append(
                f"'case_ruta' inválido en el perfil {nombre!r}: {case_ruta!r}. "
                f"Usa uno de: {', '.join(CASES_RUTA)}."
            )

    return errores


# El marcador '*' y la posición del perfil tienen que contar la misma historia: si no,
# la ruta se construye mal y SSM devuelve cero parámetros sin decir por qué.
def validar_marcador(path, convencion, perfil):
    segmentos = [s for s in path.strip("/").split("/") if s]
    marcadores = segmentos.count(MARCADOR_ENTORNO)
    posicion = perfil.get("posicion_entorno")

    if any(MARCADOR_ENTORNO in s and s != MARCADOR_ENTORNO for s in segmentos):
        return [
            f"En {path!r} el '{MARCADOR_ENTORNO}' debe ser un segmento entero "
            f"(/API/{MARCADOR_ENTORNO}/STA), no parte de un segmento."
        ]

    if posicion == "mixto" and marcadores != 1:
        return [
            f"La ruta {path!r} usa el perfil {convencion!r} ('mixto') y debe llevar "
            f"exactamente un '{MARCADOR_ENTORNO}' que marque dónde va el entorno "
            f"(tiene {marcadores})."
        ]

    if posicion != "mixto" and marcadores:
        return [
            f"La ruta {path!r} lleva un '{MARCADOR_ENTORNO}' pero su perfil {convencion!r} "
            f"tiene posicion_entorno='{posicion}', que ya decide dónde va el entorno. "
            "Usa un perfil 'mixto' o quita el marcador."
        ]

    return []


# Normalizar la configuración ya validada
def normalize_config(config):
    config["entornos"] = [str(e).lower() for e in config["entornos"]]
    config["parameter_list"] = [
        {"path": "/" + entrada["path"].strip("/"), "convencion": entrada["convencion"]}
        for entrada in config["parameter_list"]
    ]
    return config


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

    avisos = []
    if tags_activas:
        avisos = agregar_tags_a_parametros(ssm, parameters, tags_obligatorias)

    return parameters, avisos


# Feature 2: crear un parámetro nuevo con el perfil de naming de 'convencion_nuevos'
def crear_parametro(stdscr, ssm, entornos, perfil, convencion, tags_activas,
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
            "Crear nuevo parámetro (1/4): ruta",
            f"Ruta del parámetro (convención '{convencion}', sin el entorno):",
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

        problemas = validar_marcador(path, convencion, perfil)
        if problemas:
            show_message(stdscr, problemas[0], 2)
            continue
        break

    # La ruta real en AWS, ya con el entorno colocado por el perfil
    path_declarado = path
    path = build_full_path(path_declarado, perfil, entorno)

    if not show_report(
        stdscr, "Crear nuevo parámetro (2/4): confirmar la ruta",
        [f"Convención: {convencion}",
         f"Escrita:    {path_declarado}",
         f"En AWS:     {path}",
         "",
         "¿La ruta es correcta?"],
        color_pair=3, confirmar=True,
    ):
        return

    # 2. Valor (string plano o JSON)
    valor = ""
    while True:
        valor = prompt_input(
            stdscr,
            "Crear nuevo parámetro (3/4): valor",
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

    # 3. Tags obligatorias
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
                f"Crear nuevo parámetro (4/4): tags [{indice}/{len(tags_obligatorias)}]",
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
    lineas = [f"Ruta:   {path}", f"Valor:  {valor[:120]}", "Tipo:   SecureString", ""]
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

    curses.start_color()
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_GREEN, curses.COLOR_BLACK)

    environments = config['entornos']
    PARAMETER_LIST = config['parameter_list']
    NAMING = config['naming']
    TAGS_ACTIVAS = config['tags_activas']
    TAGS_OBLIGATORIAS = config['tags_obligatorias']
    OBLIGATORIAS_VACIAS = config.get('obligatorias_vacias', False)
    FICHERO_POR_RUTA = config.get('fichero_por_ruta', False)
    CONVENCION_NUEVOS = config.get('convencion_nuevos')

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

            # Crear el prefijo completo según el perfil de naming de la entrada
            full_path = build_full_path(
                selected_param["path"], NAMING[selected_param["convencion"]], selected_env
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
            export_parameters_to_file(parameters, file_name, TAGS_ACTIVAS, TAGS_OBLIGATORIAS)

            # Crear un respaldo exacto del archivo principal (valores y tags)
            export_parameters_to_file(parameters, backup_file_name, TAGS_ACTIVAS, TAGS_OBLIGATORIAS)

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
                        if change["value_changed"]:
                            # Subir o actualizar parámetros
                            ssm.put_parameter(
                                Name=param_name,
                                Value=change["value"],
                                Type='SecureString',
                                Overwrite=True
                            )
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
                    indice_a_parametros(indice), backup_file_name, TAGS_ACTIVAS, TAGS_OBLIGATORIAS
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
                            entrada["path"], NAMING[entrada["convencion"]], env
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

                        if TAGS_ACTIVAS:
                            avisos_totales.extend(
                                agregar_tags_a_parametros(ssm, parameters, TAGS_OBLIGATORIAS)
                            )
                        all_parameters.extend(parameters)

                # Crear archivo de backup total listado
                backup_file_name = "total_listed_parameters_backup.py"
                export_parameters_to_file(
                    all_parameters, backup_file_name, TAGS_ACTIVAS, TAGS_OBLIGATORIAS
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
                    parameters, backup_file_name, TAGS_ACTIVAS, TAGS_OBLIGATORIAS
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

                # Crear el prefijo completo según el perfil de naming de la entrada
                full_path = build_full_path(
                    selected_param["path"], NAMING[selected_param["convencion"]], selected_env
                )

                parameters, avisos = leer_ruta(stdscr, ssm, full_path, TAGS_ACTIVAS, TAGS_OBLIGATORIAS)
                if not parameters:
                    continue  # Regresar al menú principal

                # Crear archivo de backup con nombre claro
                backup_file_name = f"{slug_entrada(selected_param)}_{selected_env}_backup.py"
                export_parameters_to_file(
                    parameters, backup_file_name, TAGS_ACTIVAS, TAGS_OBLIGATORIAS
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
            # Crear nuevo parámetro con el perfil declarado en 'convencion_nuevos'
            crear_parametro(
                stdscr, ssm, environments, NAMING[CONVENCION_NUEVOS], CONVENCION_NUEVOS,
                TAGS_ACTIVAS, TAGS_OBLIGATORIAS, OBLIGATORIAS_VACIAS
            )

        else:
            show_message(stdscr, "Opción inválida. Inténtalo de nuevo.", 2)


# Función para crear la configuración inicial
def create_config():
    config_dir = os.path.expanduser("~/.xsoft")
    os.makedirs(config_dir, exist_ok=True)

    config_file = os.path.join(config_dir, "paramsx_config.py")
    if os.path.exists(config_file):
        print(f"El archivo de configuración ya existe en {config_file}. No se sobrescribirá.")
    else:
        # Se copia la plantilla del paquete para no duplicar el formato en dos sitios
        shutil.copyfile(PLANTILLA_PATH, config_file)
        print(f"Archivo de configuración creado en {config_file}. Por favor, edítalo con tus valores personalizados.")

# Mostrar ayuda
def show_help():
    help_text = """
ParamsX - Gestión de Parámetros de AWS SSM

Comandos disponibles:
  paramsx                Ejecuta el programa principal (requiere configuración previa).
  paramsx configure      Crea el archivo de configuración inicial en ~/.xsoft/paramsx_config.py.
  paramsx --help         Muestra esta ayuda.

Opciones del menú:
  1. Leer parámetros              Exporta a un fichero editable los parámetros de una ruta.
  2. Cargar parámetros            Compara el fichero editado y aplica los cambios en AWS.
  3. Crear Backup de parámetros   Respalda una ruta, la lista completa o toda la cuenta.
  4. Crear nuevo parámetro        Crea un parámetro nuevo con el perfil 'convencion_nuevos'.

Configuración (~/.xsoft/paramsx_config.py):
  naming            Perfiles de naming. Cada uno dice dónde va el entorno en la ruta
                    y cómo se escribe. Los nombres los eliges tú:
                      posicion_entorno  'inicio'  /rds       -> /dev/rds
                                        'final'   /API/STA   -> /API/STA/DEV
                                        'mixto'   /API/*/STA -> /API/dev/STA
                                        'ninguno' /api/auth  -> /api/auth
                      case_entorno      'lower' | 'upper' | 'capitalize'
                      case_ruta         'lower' | 'upper' | 'capitalize' | 'ninguno'
                                        (solo al crear parámetros)
  parameter_list    Lista de dicts {"path": "/rds", "convencion": "<perfil de naming>"}.
  convencion_nuevos Perfil que usan los parámetros creados con la opción 4.
  fichero_por_ruta  True -> el fichero exportado incluye la ruta en su nombre, para
                    que leer otra ruta del mismo entorno no machaque la anterior.
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
    print(help_text)

# Entry point
def entry_point():
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command in ["configure", "config", "configurar"]:
            create_config()
            return
        elif command in ["--help", "-h"]:
            show_help()
            return

    # Verificar que exista el archivo de configuración
    if not os.path.exists(CONFIG_PATH):
        print("Error: No se encontró el archivo de configuración.")
        print("Usa 'paramsx configure' para crear uno automáticamente.")
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
