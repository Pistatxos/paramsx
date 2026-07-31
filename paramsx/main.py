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
)


# Ruta de la configuración personalizada
CONFIG_PATH = os.path.expanduser("~/.xsoft/paramsx_config.py")

# Ruta de la plantilla que se copia con 'paramsx configure'
PLANTILLA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paramsx_config.py")

CONVENCIONES = ("min", "max")

MENSAJE_MIGRACION = """BREAKING CHANGE en la configuración de ParamsX
------------------------------------------------
'parameter_list' ya no es una lista de strings: ahora cada entrada es un diccionario
con su convención de naming. Edita a mano ~/.xsoft/paramsx_config.py:

    "entornos": ['dev', 'pre', 'prod'],   # SIEMPRE en minúscula
    "parameter_list": [
        {"path": "/common",   "convencion": "min"},   # /common   + dev -> /dev/common
        {"path": "/rds",      "convencion": "min"},   # /rds      + dev -> /dev/rds
        {"path": "/EMAIL",    "convencion": "max"},   # /EMAIL    + dev -> /EMAIL/DEV
        {"path": "/API/STA",  "convencion": "max"},   # /API/STA  + dev -> /API/DEV/STA
    ]

- convencion "min": convención nueva, el entorno en minúscula va SIEMPRE primero.
- convencion "max": convención legacy, el entorno en mayúscula se inserta tras el
  primer segmento de la ruta.

Ya no existe 'entornos_old': el entorno en mayúscula de las rutas "max" se deriva
de la misma lista 'entornos'."""


# Cargar configuraciones desde el archivo de usuario
def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"No se encontró el archivo de configuración en {CONFIG_PATH}")
    spec = importlib.util.spec_from_file_location("config", CONFIG_PATH)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    config = dict(modulo.configuraciones)
    # 'abac' y 'tags_obligatorias' son opcionales en el fichero del usuario:
    # si no están, se usan los valores de la plantilla que trae el paquete.
    config["abac"] = bool(getattr(modulo, "abac", plantilla_config.abac))
    config["tags_obligatorias"] = list(
        getattr(modulo, "tags_obligatorias", plantilla_config.tags_obligatorias)
    )
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
        elif not path.startswith("/"):
            errores.append(f"El 'path' debe empezar por '/': {path!r}")
        if convencion not in CONVENCIONES:
            errores.append(
                f"'convencion' inválida en {path!r}: {convencion!r}. Usa 'min' o 'max'."
            )

    return errores, avisos


# Normalizar la configuración ya validada
def normalize_config(config):
    config["entornos"] = [str(e).lower() for e in config["entornos"]]
    config["parameter_list"] = [
        {"path": "/" + entrada["path"].strip("/"), "convencion": entrada["convencion"]}
        for entrada in config["parameter_list"]
    ]
    return config


# Leer parámetros (y sus tags si abac) de una ruta ya construida
def leer_ruta(stdscr, ssm, full_path, abac, tags_obligatorias):
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
    if abac:
        avisos = agregar_tags_a_parametros(ssm, parameters, tags_obligatorias)

    return parameters, avisos


# Feature 2: crear un parámetro nuevo, siempre en convención "min"
def crear_parametro(stdscr, ssm, entornos, abac, tags_obligatorias):
    env_choice = show_environment_selection(stdscr, entornos)
    if env_choice is None:
        return
    entorno = entornos[env_choice].lower()

    # 1. Ruta completa (convención min: entorno primero y todo en minúscula)
    path = f"/{entorno}/"
    while True:
        path = prompt_input(
            stdscr,
            "Crear nuevo parámetro (1/3): ruta",
            f"Ruta completa del parámetro (convención min, empieza por /{entorno}/):",
            valor=path,
            ayuda="Ej: /{e}/common/rds/cee-dev/host  ó  /{e}/api/sta/auth/jwt_secret".format(e=entorno),
        )
        if path is None:
            return

        path = "/" + path.strip().strip("/").lower()
        segmentos = [s for s in path.strip("/").split("/") if s]

        if len(segmentos) < 2:
            show_message(stdscr, "La ruta necesita al menos /entorno/algo.", 2)
            continue
        if segmentos[0] != entorno:
            show_message(stdscr, f"El primer segmento debe ser el entorno '{entorno}'.", 2)
            path = f"/{entorno}/" + "/".join(segmentos[1:])
            continue
        break

    # 2. Valor (string plano o JSON)
    valor = ""
    while True:
        valor = prompt_input(
            stdscr,
            "Crear nuevo parámetro (2/3): valor",
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
    if abac:
        for indice, clave in enumerate(tags_obligatorias, start=1):
            predeterminado = entorno if clave == "Environment" else ""
            respuesta = prompt_input(
                stdscr,
                f"Crear nuevo parámetro (3/3): tags [{indice}/{len(tags_obligatorias)}]",
                f"Valor de la tag obligatoria '{clave}':",
                valor=predeterminado,
                ayuda="Las tags sostienen el control de acceso ABAC vía IAM: son obligatorias.",
            )
            if respuesta is None:
                return
            tags[clave] = respuesta.strip()

        faltantes = validar_tags_obligatorias(tags, tags_obligatorias)
        if faltantes:
            show_report(
                stdscr,
                "Tags obligatorias incompletas",
                [f"Faltan las tags: {', '.join(faltantes)}", "No se ha creado el parámetro."],
                color_pair=2,
            )
            return

    # Aviso de correlación de naming en RDS (no bloquea)
    aviso_rds = check_rds_correlacion(ssm, path)

    # Resumen y confirmación
    lineas = [f"Ruta:   {path}", f"Valor:  {valor[:120]}", "Tipo:   SecureString", ""]
    if abac:
        lineas.append("Tags:")
        lineas.extend([f"  {clave} = {valor_tag}" for clave, valor_tag in tags.items()])
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
    if abac and tags:
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
    ABAC = config['abac']
    TAGS_OBLIGATORIAS = config['tags_obligatorias']

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

            # Crear el prefijo completo según la convención de la entrada
            full_path = build_full_path(
                selected_param["path"], selected_param["convencion"], selected_env
            )
            show_message(stdscr, f"Buscando parámetros en: {full_path}...", 3)  # Mensaje inicial

            parameters, avisos = leer_ruta(stdscr, ssm, full_path, ABAC, TAGS_OBLIGATORIAS)
            if not parameters:
                continue  # Regresar al menú principal

            # Crear archivos si se encontraron parámetros
            file_name = f"parameters_{selected_env}.py"
            backup_file_name = f"parameters_{selected_env}_backup.py"

            # Exportar parámetros al archivo principal
            export_parameters_to_file(parameters, file_name, ABAC, TAGS_OBLIGATORIAS)

            # Crear un respaldo exacto del archivo principal (valores y tags)
            export_parameters_to_file(parameters, backup_file_name, ABAC, TAGS_OBLIGATORIAS)

            # Confirmación de archivos creados
            lineas = [
                f"Parámetros leídos de {full_path}: {len(parameters)}",
                "",
                "Archivos creados:",
                f"- {file_name}",
                f"- {backup_file_name}",
            ]
            if ABAC:
                lineas.extend([
                    "",
                    f"Tags obligatorias a rellenar: {', '.join(TAGS_OBLIGATORIAS)}",
                ])
            if avisos:
                lineas.append("")
                lineas.extend(avisos)
            show_report(stdscr, "Parámetros exportados", lineas, color_pair=3)

        elif choice == 2:
            # Cargar parámetros desde archivo
            env_choice = show_environment_selection(stdscr, environments)
            if env_choice is None:  # Si se presionó Esc
                continue  # Regresar al menú principal

            selected_env = environments[env_choice]
            file_name = f"parameters_{selected_env}.py"
            backup_file_name = f"parameters_{selected_env}_backup.py"

            if not os.path.exists(file_name) or not os.path.exists(backup_file_name):
                show_message(stdscr, f"Archivos {file_name} o {backup_file_name} no encontrados.", 2)
                continue

            try:
                # Cargar parámetros del archivo principal
                load_parameters(file_name)
            except SyntaxError as e:
                show_message(stdscr, f"ERROR: {e}", 2)
                continue  # Regresar al menú principal

            # Comparar los parámetros (valores y, si abac, también tags)
            changes = compare_parameters(file_name, backup_file_name, stdscr, ABAC)

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

            for change in changes:
                param_name = change["name"]
                tipo = change["tipo"]

                if tipo in ("Nuevo", "Modificado"):
                    # Validación bloqueante por parámetro: sin las tags obligatorias no se sube nada
                    if ABAC:
                        faltantes = validar_tags_obligatorias(change["tags"], TAGS_OBLIGATORIAS)
                        if faltantes:
                            errores.append(
                                f"✗ {param_name}: no se ha subido (ni valor ni tags). "
                                f"Faltan las tags obligatorias: {', '.join(faltantes)}."
                            )
                            continue

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
                    indice_a_parametros(indice), backup_file_name, ABAC, TAGS_OBLIGATORIAS
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

            param_choice = show_parameter_selection(stdscr, etiquetas)
            if param_choice is None:  # Si se presionó Esc
                continue  # Regresar al menú principal

            if etiquetas[param_choice] == OPCION_LISTADOS:
                # Crear backup de todos los parámetros listados
                all_parameters = []
                avisos_totales = []
                for entrada in PARAMETER_LIST:
                    for env in environments:
                        full_path = build_full_path(entrada["path"], entrada["convencion"], env)
                        try:
                            # Obtener parámetros desde AWS SSM
                            parameters = get_parameters_by_prefix(ssm, full_path)
                        except AccessDeniedError as e:
                            avisos_totales.append(e.mensaje)
                            continue
                        except ValueError:
                            # Ruta sin parámetros para ese entorno: se ignora en el backup total
                            continue

                        if ABAC:
                            avisos_totales.extend(
                                agregar_tags_a_parametros(ssm, parameters, TAGS_OBLIGATORIAS)
                            )
                        all_parameters.extend(parameters)

                # Crear archivo de backup total listado
                backup_file_name = "total_listed_parameters_backup.py"
                export_parameters_to_file(
                    all_parameters, backup_file_name, ABAC, TAGS_OBLIGATORIAS
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
                parameters, avisos = leer_ruta(stdscr, ssm, "/", ABAC, TAGS_OBLIGATORIAS)
                if not parameters:
                    continue  # Regresar al menú principal

                # Crear archivo de backup de todos los parámetros
                backup_file_name = "all_parameters_backup.py"
                export_parameters_to_file(
                    parameters, backup_file_name, ABAC, TAGS_OBLIGATORIAS
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

                # Crear el prefijo completo según la convención de la entrada
                full_path = build_full_path(
                    selected_param["path"], selected_param["convencion"], selected_env
                )

                parameters, avisos = leer_ruta(stdscr, ssm, full_path, ABAC, TAGS_OBLIGATORIAS)
                if not parameters:
                    continue  # Regresar al menú principal

                # Crear archivo de backup con nombre claro
                prefijo_fichero = selected_param["path"].strip("/").replace("/", "_")
                backup_file_name = f"{prefijo_fichero}_{selected_env}_backup.py"
                export_parameters_to_file(
                    parameters, backup_file_name, ABAC, TAGS_OBLIGATORIAS
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
            # Crear nuevo parámetro (siempre en convención "min")
            crear_parametro(stdscr, ssm, environments, ABAC, TAGS_OBLIGATORIAS)

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
  4. Crear nuevo parámetro        Crea un parámetro nuevo (siempre en convención 'min').

Configuración (~/.xsoft/paramsx_config.py):
  parameter_list    Lista de dicts {"path": "/rds", "convencion": "min"|"max"}.
                    'min' -> /dev/rds        (entorno en minúscula, primero)
                    'max' -> /API/DEV/STA    (entorno en mayúscula, tras el 1er segmento)
  abac              True para gestionar las tags obligatorias en el fichero exportado.
  tags_obligatorias Tags que sostienen el control de acceso ABAC vía IAM.

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
