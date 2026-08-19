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
    draw_header, draw_footer, show_main_menu, show_comparison_results,
    show_environment_selection, show_message, show_parameter_selection,
    get_parameters_by_prefix, delete_parameter, export_parameters_to_file,
    compare_parameters, load_parameters, show_main_menu_selection,
    AccessDeniedError, build_full_path, etiqueta_entrada, agregar_tags_a_parametros,
    validar_tags_obligatorias, aplicar_cambios_tags, check_rds_correlacion,
    agregar_descripciones_a_parametros,
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
que declara qué perfil usa. Edita a mano ~/.xsoft/paramsx_config.py:

    "entornos": ['dev', 'pre', 'prod'],   # SIEMPRE en minúscula
    "parameter_list": [
        {"path": "/common",   "perfil": "min"},   # /common   + dev -> /dev/common
        {"path": "/rds",      "perfil": "min"},   # /rds      + dev -> /dev/rds
        {"path": "/EMAIL",    "perfil": "max"},   # /EMAIL    + dev -> /EMAIL/DEV
        {"path": "/API/STA",  "perfil": "max"},   # /API/STA  + dev -> /API/STA/DEV
    ]

Los perfiles se definen en el diccionario 'perfiles' del mismo fichero, con la posición
y el case del entorno. 'min' y 'max' vienen predefinidos en la plantilla.

Ya no existe 'entornos_old': el entorno se escribe a partir de la lista 'entornos',
que va siempre en minúscula, aplicándole el 'case_entorno' del perfil."""


# Opciones que viven fuera de 'configuraciones' y son opcionales: si el usuario no las
# tiene, se usa el valor de la plantilla. Se listan para poder decirle qué le falta.
CLAVES_OPCIONALES = (
    "perfiles", "perfil_nuevos", "fichero_por_ruta", "forzar_securestring",
    "tags_activas", "obligatorias_vacias", "tags_obligatorias",
)

# Nombres antiguos que se siguen aceptando -> nombre actual. Se traducen al cargar, así
# que dentro del código solo existe el nombre nuevo.
NOMBRES_ANTIGUOS = {
    "naming": "perfiles",              # 2.2.0
    "convencion_nuevos": "perfil_nuevos",  # 2.2.0
    "abac": "tags_activas",            # 2.0.0 y 2.1.0
}


# Ejecutar el fichero de configuración del usuario y devolver el módulo resultante
def cargar_modulo_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"No se encontró el archivo de configuración en {CONFIG_PATH}")
    spec = importlib.util.spec_from_file_location("config", CONFIG_PATH)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# Cargar configuraciones desde el archivo de usuario
def load_config():
    modulo = cargar_modulo_config()

    config = dict(modulo.configuraciones)
    # Todo lo que va fuera de 'configuraciones' es opcional en el fichero del usuario:
    # si no está, se usa el valor de la plantilla que trae el paquete.
    # 'naming' es el nombre que tuvo 'perfiles' en la 2.2.0
    config["perfiles"] = dict(
        getattr(modulo, "perfiles", getattr(modulo, "naming", plantilla_config.perfiles))
    )
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
    config["forzar_securestring"] = bool(
        getattr(modulo, "forzar_securestring", plantilla_config.forzar_securestring)
    )
    # Si no se declara, los parámetros nuevos usan el primer perfil definido
    # ('convencion_nuevos' es el nombre que tuvo en la 2.2.0)
    primer_perfil = next(iter(config["perfiles"]), None)
    config["perfil_nuevos"] = (
        getattr(modulo, "perfil_nuevos", None)
        or getattr(modulo, "convencion_nuevos", None)
        or primer_perfil
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

    perfiles = config.get("perfiles")
    if not isinstance(perfiles, dict) or not perfiles:
        errores.append(
            "'perfiles' debe ser un diccionario con al menos un perfil "
            "(ver la plantilla en el propio fichero de configuración)."
        )
        perfiles = {}
    else:
        errores.extend(validar_perfiles(perfiles))

    perfil_nuevos = config.get("perfil_nuevos")
    if perfiles and perfil_nuevos not in perfiles:
        errores.append(
            f"'perfil_nuevos' apunta a un perfil que no existe: {perfil_nuevos!r}. "
            f"Perfiles definidos en 'perfiles': {', '.join(sorted(perfiles))}."
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
        nombre_perfil = perfil_de(entrada)
        if not isinstance(path, str) or not path.strip("/"):
            errores.append(f"'path' inválido o vacío en parameter_list: {entrada!r}")
            continue
        if not path.startswith("/"):
            errores.append(f"El 'path' debe empezar por '/': {path!r}")
        if nombre_perfil not in perfiles:
            errores.append(
                f"'perfil' inválido en {path!r}: {nombre_perfil!r}. "
                f"Perfiles definidos en 'perfiles': {', '.join(sorted(perfiles)) or '(ninguno)'}."
            )
            continue
        errores.extend(validar_marcador(path, nombre_perfil, perfiles[nombre_perfil]))

    # Dos entradas que resuelvan a la misma ruta no rompen nada, pero duplican trabajo
    # y confunden en el menú, así que se avisa.
    vistas = {}
    entornos_muestra = config.get("entornos") or ["dev"]
    for entrada in parameter_list:
        perfil = perfiles.get(perfil_de(entrada)) if isinstance(entrada, dict) else None
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


# Nombre del perfil que usa una entrada. 'convencion' es el nombre que tuvo esta clave
# en la 2.0, la 2.1 y la 2.2.0, y se sigue aceptando.
def perfil_de(entrada):
    if not isinstance(entrada, dict):
        return None
    return entrada.get("perfil", entrada.get("convencion"))


# Validar los perfiles. Devuelve la lista de errores.
def validar_perfiles(perfiles):
    errores = []
    for nombre, perfil in perfiles.items():
        if not isinstance(perfil, dict):
            errores.append(f"El perfil {nombre!r} debe ser un diccionario.")
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
def validar_marcador(path, nombre_perfil, perfil):
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
            f"La ruta {path!r} usa el perfil {nombre_perfil!r} ('mixto') y debe llevar "
            f"exactamente un '{MARCADOR_ENTORNO}' que marque dónde va el entorno "
            f"(tiene {marcadores})."
        ]

    if posicion != "mixto" and marcadores:
        return [
            f"La ruta {path!r} lleva un '{MARCADOR_ENTORNO}' pero su perfil {nombre_perfil!r} "
            f"tiene posicion_entorno='{posicion}', que ya decide dónde va el entorno. "
            "Usa un perfil 'mixto' o quita el marcador."
        ]

    return []


# Normalizar la configuración ya validada
def normalize_config(config):
    config["entornos"] = [str(e).lower() for e in config["entornos"]]
    # Se normaliza la clave del perfil: aunque el usuario haya escrito 'convencion',
    # dentro del programa las entradas solo tienen 'perfil'.
    config["parameter_list"] = [
        {"path": "/" + entrada["path"].strip("/"), "perfil": perfil_de(entrada)}
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

    curses.start_color()
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_GREEN, curses.COLOR_BLACK)

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
  paramsx                   Ejecuta el programa principal (requiere configuración previa).
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
