import time
import os
from .text import HEADER_ASCII, FOOTER_TEXT
import curses

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
        except Exception as e:
            raise RuntimeError(f"Error al obtener parámetros: {e}")

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

# Función para borrar los parámetros
def delete_parameter(ssm_client, parameter_name):
    try:
        ssm_client.delete_parameter(Name=parameter_name)
        print(f"Parámetro eliminado: {parameter_name}")
    except Exception as e:
        print(f"Error al eliminar el parámetro {parameter_name}: {e}")

# Función para exportar parámetros a un archivo
def export_parameters_to_file(parameters, file_path):
    with open(file_path, 'w') as f:
        f.write("# PARAMS exportados\n")
        f.write("parametros = [\n")
        for param in parameters:
            parameter_name = param['parameter_name']
            parameter_value = param['parameter_value']
            # Usar triple comillas para valores largos
            f.write(f"    {{'parameter_name': '{parameter_name}',\n")
            f.write(f"     'parameter_value': \"\"\"{parameter_value}\"\"\"}},\n\n")
        f.write("]\n")

# Función para comparar parámetros y mostrar las diferencias
def compare_parameters(file_path, backup_file_path, stdscr):
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
    current_params = current_scope.get('parametros', [])
    backup_params = backup_scope.get('parametros', [])

    # Comparar parámetros
    changes = []
    current_dict = {p['parameter_name']: p['parameter_value'] for p in current_params}
    backup_dict = {p['parameter_name']: p['parameter_value'] for p in backup_params}

    for key in current_dict:
        if key not in backup_dict:
            changes.append((key, "Nuevo", f"{key} - Nuevo"))
        elif current_dict[key] != backup_dict[key]:
            changes.append((key, "Modificado", f"{key} - Modificado"))

    for key in backup_dict:
        if key not in current_dict:
            changes.append((key, "Eliminado", f"{key} - Eliminado"))

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
        stdscr.addstr(start_line, 0, title.center(max_x, "-"))

        # Calcular el rango visible incluyendo el buffer
        visible_changes = changes[scroll_offset:scroll_offset + visible_height]

        for i, change in enumerate(visible_changes, start=1 + scroll_offset):
            comment = f"{i}. {change[0]} - {change[1]}"
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
    stdscr.addstr(start_line + 3, 0, "Elija una opción (1/2): ")

# Mostrar selección de parámetros
def show_parameter_selection(stdscr, options):
    stdscr.clear()
    draw_header(stdscr)
    start_line = HEADER_ASCII.count("\n") + 1  # Calcula el inicio después del header
    stdscr.addstr(start_line, 0, "Seleccione un parámetro para leer:".center(60, "-"))
    for idx, option in enumerate(options, start=1):
        stdscr.addstr(start_line + idx, 0, f"{idx}. {option}")
    draw_footer(stdscr)
    stdscr.refresh()

    while True:
        key = stdscr.getkey()
        if key == '\x1b':  # Si se presiona Esc
            return None  # Cancelar selección
        try:
            choice = int(key) - 1
            if 0 <= choice < len(options):
                return choice
        except ValueError:
            pass  # Ignorar entradas inválidas

# Mostrar selección de entorno
def show_environment_selection(stdscr, environments):
    stdscr.clear()
    draw_header(stdscr)
    start_line = HEADER_ASCII.count("\n") + 1
    stdscr.addstr(start_line, 0, "Seleccione el entorno:".center(60, "-"))
    for idx, env in enumerate(environments, start=1):
        stdscr.addstr(start_line + idx, 0, f"{idx}. {env}")
    draw_footer(stdscr)
    stdscr.refresh()

    while True:
        key = stdscr.getkey()
        if key == '\x1b':  # Si se presiona Esc
            return None  # Cancelar selección
        try:
            choice = int(key) - 1
            if 0 <= choice < len(environments):
                return choice
        except ValueError:
            pass  # Ignorar entradas inválidas

# Pantalla de confirmación o resultados
def show_message(stdscr, message, color_pair=1):
    stdscr.clear()
    draw_header(stdscr)
    start_line = HEADER_ASCII.count("\n") + 1
    stdscr.addstr(start_line, 0, message.center(60, " "), curses.color_pair(color_pair))
    draw_footer(stdscr)
    stdscr.refresh()
    time.sleep(3)

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