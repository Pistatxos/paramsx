import time
import os
import textwrap
from .text import HEADER_ASCII, FOOTER_TEXT
import curses
from botocore.exceptions import ClientError

# Prefijo con el que se serializan las tags en el fichero exportado: tagApplication, tagOwner...
TAG_FIELD_PREFIX = "tag"


class AccessDeniedError(Exception):
    """El rol IAM del usuario no tiene permisos sobre esa ruta o recurso de SSM."""

    def __init__(self, path, sugerir_acotar=True):
        self.path = path
        mensaje = f"⚠ No tienes permisos para leer: {path} — pídele a un admin que te dé acceso"
        if sugerir_acotar:
            mensaje += (
                ", o acota la ruta en tu parameter_list a algo más específico "
                f"(ej. {path.rstrip('/')}/<sub-ruta>)."
            )
        else:
            mensaje += "."
        self.mensaje = mensaje
        super().__init__(mensaje)


def _codigo_error(error):
    return error.response.get("Error", {}).get("Code", "")


# Valores admitidos en un perfil de naming
POSICIONES_ENTORNO = ("inicio", "final", "mixto", "ninguno")
CASES_ENTORNO = ("lower", "upper", "capitalize")
CASES_RUTA = ("lower", "upper", "capitalize", "ninguno")

# Marcador que indica, en las rutas de perfiles "mixto", dónde va el entorno
MARCADOR_ENTORNO = "*"


# Escribir el entorno como lo pide el perfil: dev -> dev | DEV | Dev
def aplicar_case_entorno(entorno, case_entorno):
    if case_entorno == "upper":
        return entorno.upper()
    if case_entorno == "capitalize":
        return entorno.capitalize()
    return entorno.lower()


# Escribir la ruta como pide el perfil al crear un parámetro nuevo. 'capitalize' va
# segmento a segmento: str.capitalize() sobre la ruta entera pasaría a minúscula todo
# lo que hay detrás del primer carácter.
def aplicar_case_ruta(path, case_ruta):
    if case_ruta == "lower":
        return path.lower()
    if case_ruta == "upper":
        return path.upper()
    if case_ruta == "capitalize":
        return "/" + "/".join(s.capitalize() for s in path.strip("/").split("/") if s)
    return path


# Construir la ruta completa aplicando el perfil de naming de la entrada.
# Las tres posiciones son la misma operación: se normaliza la ruta a una plantilla con
# un único marcador y se sustituye por el entorno. "ninguno" no lleva marcador.
def build_full_path(path, perfil, entorno):
    segmentos = [s for s in path.strip("/").split("/") if s]
    if not segmentos:
        raise ValueError(f"Ruta vacía en parameter_list: {path!r}")

    posicion = perfil.get("posicion_entorno")
    if posicion not in POSICIONES_ENTORNO:
        raise ValueError(
            f"'posicion_entorno' desconocida {posicion!r} para la ruta {path!r}. "
            f"Usa una de: {', '.join(POSICIONES_ENTORNO)}."
        )

    if posicion == "ninguno":
        return "/" + "/".join(segmentos)

    if posicion == "inicio":
        plantilla = [MARCADOR_ENTORNO, *segmentos]
    elif posicion == "final":
        plantilla = [*segmentos, MARCADOR_ENTORNO]
    else:  # mixto: el marcador ya viene puesto en la ruta
        if segmentos.count(MARCADOR_ENTORNO) != 1:
            raise ValueError(
                f"La ruta {path!r} usa un perfil 'mixto' y debe llevar exactamente un "
                f"'{MARCADOR_ENTORNO}' como segmento para marcar dónde va el entorno."
            )
        plantilla = segmentos

    entorno_escrito = aplicar_case_entorno(entorno, perfil.get("case_entorno", "lower"))
    return "/" + "/".join(entorno_escrito if s == MARCADOR_ENTORNO else s for s in plantilla)


# Trozo de nombre de fichero derivado de una entrada de parameter_list:
# {"path": "/API/*/STA", "convencion": "mixto_max"} -> API_env_STA__mixto_max
# Lleva la posición del marcador y el perfil porque dos entradas distintas pueden
# compartir la ruta declarada (con perfiles distintos, o con el entorno en otro sitio)
# y apuntar a rutas de AWS diferentes: sus ficheros no se pueden pisar.
def slug_entrada(entrada):
    segmentos = [s for s in entrada["path"].strip("/").split("/") if s]
    ruta = "_".join("env" if s == MARCADOR_ENTORNO else s for s in segmentos)
    convencion = entrada.get("convencion")
    return f"{ruta}__{convencion}" if convencion else ruta


# Etiqueta legible de una entrada de parameter_list para los menús
def etiqueta_entrada(entrada):
    return f"{entrada['path']}  [{entrada['convencion']}]"


# Ficheros exportados que hay en el directorio actual listos para cargar: los que
# conservan su backup al lado. Se listan tal cual están en disco, sin depender de la
# parameter_list, para que también aparezcan los de una ruta que ya hayas quitado de
# la configuración. Devuelve una lista de (fichero, backup).
def ficheros_cargables(directorio="."):
    cargables = []
    try:
        nombres = sorted(os.listdir(directorio))
    except OSError:
        return cargables

    for nombre in nombres:
        if not nombre.startswith("parameters_") or not nombre.endswith(".py"):
            continue
        if nombre.endswith("_backup.py"):
            continue
        backup = f"{nombre[:-3]}_backup.py"
        if os.path.exists(os.path.join(directorio, backup)):
            cargables.append((nombre, backup))

    return cargables


# Función para obtener parámetros con un entorno específico
def get_parameters_by_prefix(ssm, prefix):
    parameters = []
    next_token = None

    while True:
        request_args = {
            "Path": prefix,
            "WithDecryption": True,
            "Recursive": True,
        }

        if next_token:
            request_args["NextToken"] = next_token

        try:
            response = ssm.get_parameters_by_path(**request_args)
        except ClientError as e:
            # Solo el acceso denegado se traduce a un mensaje amable; el resto se propaga tal cual
            if _codigo_error(e) == "AccessDeniedException":
                raise AccessDeniedError(prefix) from None
            raise

        for param in response.get('Parameters', []):
            parameters.append({
                "parameter_name": param['Name'],
                "parameter_value": param['Value']
            })

        next_token = response.get('NextToken')
        if not next_token:
            break

    if not parameters:
        raise ValueError(f"No se encontraron parámetros con el prefijo: {prefix}")

    return parameters


# Comprobar si existe algún parámetro bajo un prefijo (None = no se pudo comprobar por permisos)
def existe_prefijo(ssm, prefix):
    try:
        response = ssm.get_parameters_by_path(Path=prefix, Recursive=True, MaxResults=1)
    except ClientError as e:
        if _codigo_error(e) == "AccessDeniedException":
            return None
        raise
    return bool(response.get('Parameters', []))


# Aviso de naming: en RDS el {nombre-servicio} del común y del privado deben coincidir
def check_rds_correlacion(ssm, path):
    segmentos = [s for s in path.strip("/").split("/") if s]
    if len(segmentos) < 3:
        return None

    entorno = segmentos[0]
    if segmentos[1] == "common" and segmentos[2] == "rds" and len(segmentos) >= 4:
        nombre_servicio = segmentos[3]
        contraparte = f"/{entorno}/rds/{nombre_servicio}"
        que_falta = "el privado (user/password)"
    elif segmentos[1] == "rds":
        nombre_servicio = segmentos[2]
        contraparte = f"/{entorno}/common/rds/{nombre_servicio}"
        que_falta = "el común (host/port/database)"
    else:
        return None

    existe = existe_prefijo(ssm, contraparte)
    if existe is None:
        return (
            f"ℹ No se pudo verificar la correlación de naming con {contraparte} "
            "(sin permisos de lectura sobre esa ruta)."
        )
    if existe:
        return None

    return (
        f"⚠ Posible inconsistencia de naming: no existe ningún parámetro en {contraparte}, "
        f"así que falta {que_falta} para '{nombre_servicio}'. "
        "Revisa que el segmento {nombre-servicio} coincida exactamente en común y privado."
    )


# Función para leer las tags actuales de un parámetro
def get_parameter_tags(ssm, parameter_name):
    try:
        response = ssm.list_tags_for_resource(
            ResourceType="Parameter",
            ResourceId=parameter_name,
        )
    except ClientError as e:
        if _codigo_error(e) == "AccessDeniedException":
            raise AccessDeniedError(parameter_name, sugerir_acotar=False) from None
        raise

    # Las tags de sistema (aws:*) no se pueden editar, así que no se exportan
    return {
        t["Key"]: t["Value"]
        for t in response.get("TagList", [])
        if not t["Key"].startswith("aws:")
    }


# Rellenar cada parámetro con sus tags de AWS. Devuelve la lista de avisos no bloqueantes.
def agregar_tags_a_parametros(ssm, parameters, tags_obligatorias):
    avisos = []
    for param in parameters:
        try:
            tags = get_parameter_tags(ssm, param["parameter_name"])
        except AccessDeniedError:
            tags = {}
            avisos.append(
                f"⚠ Sin permisos para leer las tags de {param['parameter_name']} "
                "(se exportan vacías)."
            )

        for clave in tags_obligatorias:
            param[f"{TAG_FIELD_PREFIX}{clave}"] = tags.get(clave, "")
        # Las tags que ya existen en AWS y no están en la lista obligatoria se conservan
        for clave, valor in tags.items():
            if clave not in tags_obligatorias:
                param[f"{TAG_FIELD_PREFIX}{clave}"] = valor

    return avisos


# Extraer del dict de un parámetro sus tags (tagOwner -> Owner)
def extraer_tags(param):
    tags = {}
    for clave, valor in param.items():
        if clave.startswith(TAG_FIELD_PREFIX) and len(clave) > len(TAG_FIELD_PREFIX):
            tags[clave[len(TAG_FIELD_PREFIX):]] = "" if valor is None else str(valor)
    return tags


# Comprobar qué tags obligatorias faltan (vacías o ausentes)
def validar_tags_obligatorias(tags, tags_obligatorias):
    return [clave for clave in tags_obligatorias if not str(tags.get(clave, "")).strip()]


# Aplicar cambios de tags sobre un parámetro existente
def aplicar_cambios_tags(ssm, parameter_name, tags_set=None, tags_remove=None):
    if tags_set:
        ssm.add_tags_to_resource(
            ResourceType="Parameter",
            ResourceId=parameter_name,
            Tags=[{"Key": k, "Value": v} for k, v in tags_set.items()],
        )
    if tags_remove:
        ssm.remove_tags_from_resource(
            ResourceType="Parameter",
            ResourceId=parameter_name,
            TagKeys=list(tags_remove),
        )


# Función para borrar los parámetros
def delete_parameter(ssm_client, parameter_name):
    try:
        ssm_client.delete_parameter(Name=parameter_name)
    except ClientError as e:
        if _codigo_error(e) == "AccessDeniedException":
            raise AccessDeniedError(parameter_name, sugerir_acotar=False) from None
        raise


def _escapar_valor_tag(valor):
    return (
        str(valor)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def _orden_tags(param, tags_obligatorias):
    presentes = extraer_tags(param)
    extras = [c for c in presentes if c not in tags_obligatorias]
    return list(tags_obligatorias) + sorted(extras)


# Función para exportar parámetros a un archivo
def export_parameters_to_file(parameters, file_path, tags_activas=False, tags_obligatorias=None):
    tags_obligatorias = tags_obligatorias or []

    with open(file_path, 'w') as f:
        f.write("# PARAMS exportados\n")
        f.write("parametros = [\n")
        for param in parameters:
            parameter_name = param['parameter_name']
            parameter_value = param['parameter_value']
            f.write(f"    {{'parameter_name': '{parameter_name}',\n")

            if not tags_activas:
                # Usar triple comillas para valores largos
                f.write(f"     'parameter_value': \"\"\"{parameter_value}\"\"\"}},\n\n")
                continue

            f.write(f"     'parameter_value': \"\"\"{parameter_value}\"\"\",\n")
            for clave in _orden_tags(param, tags_obligatorias):
                valor = param.get(f"{TAG_FIELD_PREFIX}{clave}", "")
                f.write(f"     '{TAG_FIELD_PREFIX}{clave}': \"{_escapar_valor_tag(valor)}\",\n")
            f.write("    },\n\n")
        f.write("]\n")


def indexar_parametros(parametros):
    return {
        p['parameter_name']: {
            "value": p.get('parameter_value', ""),
            "tags": extraer_tags(p),
        }
        for p in parametros
    }


# Reconstruir la lista de parámetros exportable desde un índice (para resincronizar backups)
def indice_a_parametros(indice):
    parametros = []
    for nombre, datos in indice.items():
        param = {"parameter_name": nombre, "parameter_value": datos["value"]}
        for clave, valor in datos["tags"].items():
            param[f"{TAG_FIELD_PREFIX}{clave}"] = valor
        parametros.append(param)
    return parametros


def _diff_tags(tags_actuales, tags_backup):
    """Devuelve (tags_a_escribir, tags_a_borrar) comparando fichero editado vs backup."""
    tags_set = {}
    tags_remove = []

    for clave, valor in tags_actuales.items():
        valor = str(valor)
        anterior = tags_backup.get(clave)
        if valor.strip() == "":
            # Campo vaciado a mano = borrar la tag en AWS (si existía)
            if anterior not in (None, ""):
                tags_remove.append(clave)
        elif valor != anterior:
            tags_set[clave] = valor

    for clave, anterior in tags_backup.items():
        # Línea de tag borrada del fichero
        if clave not in tags_actuales and str(anterior).strip() != "":
            tags_remove.append(clave)

    return tags_set, sorted(set(tags_remove))


# Función para comparar parámetros y mostrar las diferencias
def compare_parameters(file_path, backup_file_path, stdscr=None, tags_activas=False):
    if not os.path.exists(file_path) or not os.path.exists(backup_file_path):
        return None

    # Usar diccionarios específicos para cargar los archivos
    current_scope = {}
    backup_scope = {}

    with open(file_path, 'r') as f:
        exec(f.read(), current_scope)

    with open(backup_file_path, 'r') as f:
        exec(f.read(), backup_scope)

    # Extraer los parámetros de cada archivo
    current_dict = indexar_parametros(current_scope.get('parametros', []))
    backup_dict = indexar_parametros(backup_scope.get('parametros', []))

    changes = []

    for nombre, actual in current_dict.items():
        anterior = backup_dict.get(nombre)

        if anterior is None:
            changes.append({
                "name": nombre,
                "tipo": "Nuevo",
                "detalle": "nuevo parámetro",
                "value": actual["value"],
                "tags": actual["tags"],
                "value_changed": True,
                "tags_set": {k: v for k, v in actual["tags"].items() if str(v).strip()},
                "tags_remove": [],
            })
            continue

        value_changed = actual["value"] != anterior["value"]
        tags_set, tags_remove = ({}, [])
        if tags_activas:
            tags_set, tags_remove = _diff_tags(actual["tags"], anterior["tags"])

        if not value_changed and not tags_set and not tags_remove:
            continue

        detalles = []
        if value_changed:
            detalles.append("valor")
        if tags_set:
            detalles.append(f"tags: {', '.join(sorted(tags_set))}")
        if tags_remove:
            detalles.append(f"tags borradas: {', '.join(tags_remove)}")

        changes.append({
            "name": nombre,
            "tipo": "Modificado",
            "detalle": " | ".join(detalles),
            "value": actual["value"],
            "tags": actual["tags"],
            "value_changed": value_changed,
            "tags_set": tags_set,
            "tags_remove": tags_remove,
        })

    for nombre in backup_dict:
        if nombre not in current_dict:
            changes.append({
                "name": nombre,
                "tipo": "Eliminado",
                "detalle": "se borrará de AWS",
                "value": backup_dict[nombre]["value"],
                "tags": backup_dict[nombre]["tags"],
                "value_changed": False,
                "tags_set": {},
                "tags_remove": [],
            })

    return changes


# Mostrar contenido comparado
def show_comparison_results(stdscr, changes):
    stdscr.clear()
    draw_header(stdscr)

    max_y, max_x = stdscr.getmaxyx()  # Tamaño del terminal
    start_line = HEADER_ASCII.count("\n") + 1  # Reservar espacio para el header
    visible_height = max_y - start_line - 3  # Espacio visible en el terminal (sin header/footer)
    scroll_offset = 0  # Controlar desde qué línea se empieza a mostrar
    buffer_lines = 2  # Número de líneas adicionales para mostrar al final

    while True:
        stdscr.clear()
        draw_header(stdscr)

        # Mostrar encabezado de la lista con cantidad y guía de navegación
        title = f"Cambios detectados ({len(changes)}) - Usa ↑ y ↓ para navegar - Intro confirmar y Esc para salir"
        stdscr.addstr(start_line, 0, title.center(max_x, "-")[:max_x - 1])

        # Calcular el rango visible incluyendo el buffer
        visible_changes = changes[scroll_offset:scroll_offset + visible_height]

        for i, change in enumerate(visible_changes, start=1 + scroll_offset):
            comment = f"{i}. {change['name']} - {change['tipo']} ({change['detalle']})"
            truncated_comment = comment[:max_x - 1]  # Truncar si excede el ancho
            stdscr.addstr(start_line + i - scroll_offset, 0, truncated_comment)

        # Mostrar footer vacío o decorativo
        draw_footer(stdscr)

        # Actualizar pantalla
        stdscr.refresh()

        # Capturar entrada del usuario
        key = stdscr.getkey()

        # Manejar teclas de desplazamiento
        if key == "KEY_UP" and scroll_offset > 0:
            scroll_offset -= 1
        elif key == "KEY_DOWN" and scroll_offset + visible_height < len(changes) + buffer_lines:
            scroll_offset += 1
        elif key == '\x1b':  # Presionar Esc para salir
            return False
        elif key == '\n':  # Presionar Enter para confirmar
            return True


# Función para mostrar el header personalizado
def draw_header(stdscr):
    max_y, max_x = stdscr.getmaxyx()
    separator = "=" * max_x
    stdscr.addstr(0, 0, separator)  # Línea superior del header

    # Mostrar HEADER_ASCII línea por línea sin strip
    header_lines = HEADER_ASCII.split("\n")  # No eliminar espacios ni líneas vacías
    last_line_index = 0  # Guardar el índice de la última línea válida

    for i, line in enumerate(header_lines, start=1):
        if line.strip():  # Solo imprimir líneas no vacías
            stdscr.addstr(i, 0, line)
            last_line_index = i  # Actualizar la posición de la última línea visible

    stdscr.addstr(last_line_index + 1, 0, separator)  # Línea inferior después de la última línea del header

# Función para mostrar el footer personalizado
def draw_footer(stdscr):
    rows, cols = stdscr.getmaxyx()  # Tamaño del terminal
    exit_text = "Pulsa 'Esc' para volver o salir"  # Mensaje adicional
    footer_text = FOOTER_TEXT[:cols - 1]  # Recortar el texto si es más ancho que el terminal
    separator = "-" * cols  # Separador completo ajustado al ancho

    # Asegurarse de que hay espacio suficiente para el footer
    if rows > 2:  # Verifica que haya espacio mínimo para el footer
        try:
            stdscr.addstr(rows - 3, 0, exit_text.center(cols, " "))  # Centrar el texto de salida
            stdscr.addstr(rows - 2, 0, separator)  # Línea separadora
            stdscr.addstr(rows - 1, 0, footer_text.center(cols - 1, " "))  # Centrar el texto
        except curses.error:
            pass  # Ignorar errores si no hay espacio suficiente

# Mostrar contenido principal del menú
def show_main_menu(stdscr):
    start_line = HEADER_ASCII.count("\n") + 1  # Calcula dónde termina el header
    stdscr.addstr(start_line, 0, "1. Leer parámetros".ljust(60))
    stdscr.addstr(start_line + 1, 0, "2. Cargar parámetros desde archivo".ljust(60))
    stdscr.addstr(start_line + 2, 0, "3. Crear Backup de parámetros".ljust(60))
    stdscr.addstr(start_line + 3, 0, "4. Crear nuevo parámetro".ljust(60))
    stdscr.addstr(start_line + 4, 0, "Elija una opción (1/2/3/4): ")

# Mostrar menú principal con navegación
def show_main_menu_selection(stdscr):
    selected = 0
    buffer = ""
    options = [
        "Leer parámetros",
        "Cargar parámetros desde archivo",
        "Crear Backup de parámetros",
        "Crear nuevo parámetro"
    ]

    def render():
        stdscr.clear()
        draw_header(stdscr)
        start_line = HEADER_ASCII.count("\n") + 1

        for idx, option in enumerate(options, start=1):
            line = f"{idx}. {option}"
            if idx - 1 == selected:
                stdscr.addstr(start_line + idx - 1, 0, line, curses.A_REVERSE)
            else:
                stdscr.addstr(start_line + idx - 1, 0, line)

        # Mostrar instrucciones y buffer de entrada
        input_line = start_line + len(options) + 1
        stdscr.addstr(input_line, 0, f"Usa ↑/↓ para navegar, Enter para seleccionar, o escribe número: {buffer}")
        draw_footer(stdscr)
        stdscr.refresh()

    render()

    while True:
        key = stdscr.getkey()

        if key == '\x1b':  # Esc
            return None
        elif key == 'KEY_UP':
            if selected > 0:
                selected -= 1
            buffer = ""
            render()
        elif key == 'KEY_DOWN':
            if selected < len(options) - 1:
                selected += 1
            buffer = ""
            render()
        elif key == '\n' or key == '\r':  # Enter
            if buffer.isdigit():
                choice = int(buffer) - 1
                if 0 <= choice < len(options):
                    return choice
                buffer = ""
                render()
            else:
                return selected
        elif key == 'KEY_BACKSPACE' or key == '\b' or key == '\x7f':
            buffer = buffer[:-1]
            render()
        elif key.isdigit():
            buffer += key
            render()
        elif key.lower() == 'q':
            return None

# Mostrar selección de parámetros
def show_parameter_selection(stdscr, options, titulo="Seleccione un parámetro para leer:"):
    selected = 0
    buffer = ""
    scroll_offset = [0]  # Usar lista para que sea mutable desde render()

    def render():
        stdscr.clear()
        draw_header(stdscr)
        start_line = HEADER_ASCII.count("\n") + 1
        max_y, max_x = stdscr.getmaxyx()

        stdscr.addstr(start_line, 0, titulo.center(60, "-")[:max_x - 1])

        # Calcular cuántas líneas podemos mostrar
        available_height = max_y - start_line - 4  # Dejar espacio para footer e instrucciones
        visible_count = min(len(options), available_height)

        # Ajustar scroll para mantener selected visible
        if selected < scroll_offset[0]:
            scroll_offset[0] = selected
        elif selected >= scroll_offset[0] + visible_count:
            scroll_offset[0] = selected - visible_count + 1

        # Mostrar solo las opciones visibles
        for i in range(visible_count):
            actual_idx = scroll_offset[0] + i
            if actual_idx < len(options):
                # Truncar al ancho del terminal: los nombres de fichero y las rutas
                # largas desmaquetarían la lista al hacer wrap
                line = f"{actual_idx + 1}. {options[actual_idx]}"[:max_x - 1]
                if actual_idx == selected:
                    stdscr.addstr(start_line + i + 1, 0, line, curses.A_REVERSE)
                else:
                    stdscr.addstr(start_line + i + 1, 0, line)

        # Mostrar info de scroll si es necesario
        if len(options) > visible_count:
            scroll_info = f"({scroll_offset[0] + 1}-{min(scroll_offset[0] + visible_count, len(options))} de {len(options)})"
            stdscr.addstr(start_line + visible_count + 1, 0, scroll_info[:max_x - 1])

        # Mostrar instrucciones y buffer de entrada
        input_line = start_line + visible_count + 2
        if len(options) > visible_count:
            input_line += 1  # Una línea extra para el indicador de scroll

        # Solo mostrar instrucciones si hay espacio
        if input_line < max_y - 2:
            instrucciones = (
                f"Usa ↑/↓ para navegar, Enter para seleccionar, o escribe número: {buffer}"
            )
            stdscr.addstr(input_line, 0, instrucciones[:max_x - 1])
        draw_footer(stdscr)
        stdscr.refresh()

    render()

    while True:
        key = stdscr.getkey()

        if key == '\x1b':  # Esc
            return None
        elif key == 'KEY_UP':
            if selected > 0:
                selected -= 1
            buffer = ""
            render()
        elif key == 'KEY_DOWN':
            if selected < len(options) - 1:
                selected += 1
            buffer = ""
            render()
        elif key == '\n' or key == '\r':  # Enter
            if buffer.isdigit():
                choice = int(buffer) - 1
                if 0 <= choice < len(options):
                    return choice
                buffer = ""
                render()
            else:
                return selected
        elif key == 'KEY_BACKSPACE' or key == '\b' or key == '\x7f':
            buffer = buffer[:-1]
            render()
        elif key.isdigit():
            buffer += key
            render()
        elif key.lower() == 'q':
            return None

# Mostrar selección de entorno
def show_environment_selection(stdscr, environments):
    selected = 0
    buffer = ""

    def render():
        stdscr.clear()
        draw_header(stdscr)
        start_line = HEADER_ASCII.count("\n") + 1
        stdscr.addstr(start_line, 0, "Seleccione el entorno:".center(60, "-"))

        for idx, env in enumerate(environments, start=1):
            line = f"{idx}. {env}"
            if idx - 1 == selected:
                stdscr.addstr(start_line + idx, 0, line, curses.A_REVERSE)
            else:
                stdscr.addstr(start_line + idx, 0, line)

        # Mostrar instrucciones y buffer de entrada
        input_line = start_line + len(environments) + 2
        stdscr.addstr(input_line, 0, f"Usa ↑/↓ para navegar, Enter para seleccionar, o escribe número: {buffer}")
        draw_footer(stdscr)
        stdscr.refresh()

    render()

    while True:
        key = stdscr.getkey()

        if key == '\x1b':  # Esc
            return None
        elif key == 'KEY_UP':
            if selected > 0:
                selected -= 1
            buffer = ""
            render()
        elif key == 'KEY_DOWN':
            if selected < len(environments) - 1:
                selected += 1
            buffer = ""
            render()
        elif key == '\n' or key == '\r':  # Enter
            if buffer.isdigit():
                choice = int(buffer) - 1
                if 0 <= choice < len(environments):
                    return choice
                buffer = ""
                render()
            else:
                return selected
        elif key == 'KEY_BACKSPACE' or key == '\b' or key == '\x7f':
            buffer = buffer[:-1]
            render()
        elif key.isdigit():
            buffer += key
            render()
        elif key.lower() == 'q':
            return None

# Pantalla de confirmación o resultados
def show_message(stdscr, message, color_pair=1):
    stdscr.clear()
    draw_header(stdscr)
    max_y, max_x = stdscr.getmaxyx()
    start_line = HEADER_ASCII.count("\n") + 1
    # Ajustar el mensaje al ancho del terminal para no romper la pantalla
    lineas = textwrap.wrap(str(message), width=max(20, max_x - 2)) or [""]
    for i, linea in enumerate(lineas):
        try:
            texto = linea.center(60, " ") if len(lineas) == 1 else linea
            stdscr.addstr(start_line + i, 0, texto[:max_x - 1], curses.color_pair(color_pair))
        except curses.error:
            pass
    draw_footer(stdscr)
    stdscr.refresh()
    time.sleep(3)


# Informe multilínea con scroll. Si confirmar=True devuelve True (Enter) / False (Esc).
def show_report(stdscr, titulo, lineas, color_pair=1, confirmar=False):
    max_y, max_x = stdscr.getmaxyx()
    ancho = max(20, max_x - 2)

    # Aplanar y ajustar el texto al ancho del terminal
    envueltas = []
    for linea in lineas:
        if not str(linea).strip():
            envueltas.append("")
            continue
        envueltas.extend(textwrap.wrap(str(linea), width=ancho) or [""])

    scroll = 0
    while True:
        stdscr.clear()
        draw_header(stdscr)
        max_y, max_x = stdscr.getmaxyx()
        start_line = HEADER_ASCII.count("\n") + 1
        visible = max(1, max_y - start_line - 4)

        pie = "Enter confirmar / Esc cancelar" if confirmar else "Enter o Esc para volver"
        cabecera = f"{titulo} - ↑/↓ para navegar - {pie}"
        try:
            stdscr.addstr(start_line, 0, cabecera.center(max_x, "-")[:max_x - 1],
                          curses.color_pair(color_pair))
        except curses.error:
            pass

        for i, linea in enumerate(envueltas[scroll:scroll + visible]):
            try:
                stdscr.addstr(start_line + 1 + i, 0, linea[:max_x - 1])
            except curses.error:
                pass

        if len(envueltas) > visible:
            info = f"({scroll + 1}-{min(scroll + visible, len(envueltas))} de {len(envueltas)})"
            try:
                stdscr.addstr(start_line + 1 + visible, 0, info[:max_x - 1])
            except curses.error:
                pass

        draw_footer(stdscr)
        stdscr.refresh()

        key = stdscr.getkey()
        if key == 'KEY_UP' and scroll > 0:
            scroll -= 1
        elif key == 'KEY_DOWN' and scroll + visible < len(envueltas):
            scroll += 1
        elif key == '\x1b':
            return False
        elif key in ('\n', '\r'):
            return True


# Pedir un texto por teclado. Devuelve None si el usuario pulsa Esc.
def prompt_input(stdscr, titulo, etiqueta, valor="", permitir_vacio=False, ayuda=""):
    buffer = valor
    error = ""

    while True:
        stdscr.clear()
        draw_header(stdscr)
        max_y, max_x = stdscr.getmaxyx()
        start_line = HEADER_ASCII.count("\n") + 1

        try:
            stdscr.addstr(start_line, 0, titulo.center(max_x, "-")[:max_x - 1])
            fila = start_line + 1
            for linea in textwrap.wrap(etiqueta, width=max(20, max_x - 2)):
                stdscr.addstr(fila, 0, linea[:max_x - 1])
                fila += 1
            if ayuda:
                for linea in textwrap.wrap(ayuda, width=max(20, max_x - 2)):
                    stdscr.addstr(fila, 0, linea[:max_x - 1])
                    fila += 1
            fila += 1
            stdscr.addstr(fila, 0, f"> {buffer}"[:max_x - 1], curses.A_REVERSE)
            fila += 2
            if error:
                for linea in textwrap.wrap(error, width=max(20, max_x - 2)):
                    stdscr.addstr(fila, 0, linea[:max_x - 1], curses.color_pair(2))
                    fila += 1
            stdscr.addstr(fila + 1, 0, "Enter para aceptar - Esc para cancelar"[:max_x - 1])
        except curses.error:
            pass

        draw_footer(stdscr)
        stdscr.refresh()

        try:
            key = stdscr.getkey()
        except curses.error:
            continue

        if key == '\x1b':
            return None
        if key in ('\n', '\r'):
            if not buffer.strip() and not permitir_vacio:
                error = "Este campo es obligatorio."
                continue
            return buffer
        if key in ('KEY_BACKSPACE', '\b', '\x7f'):
            buffer = buffer[:-1]
            error = ""
            continue
        if len(key) == 1 and key.isprintable():
            buffer += key
            error = ""


# Errores varios
def load_parameters(file_path):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"El archivo {file_path} no existe.")

    param_scope = {}
    try:
        with open(file_path, 'r') as f:
            exec(f.read(), param_scope)  # Ejecuta el archivo en el contexto de param_scope
    except SyntaxError as e:
        raise SyntaxError(
            f"Error de sintaxis en {file_path}.\nRevisa las comillas o el formato del archivo."
        )

    return param_scope.get('parametros', [])
