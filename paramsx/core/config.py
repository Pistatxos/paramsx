import ast
import json
import os

from .. import paramsx_config as plantilla_config
from .rutas import (
    POSICIONES_ENTORNO, CASES_ENTORNO, CASES_RUTA, build_full_path, validar_marcador,
)


# Ruta de la configuración personalizada
CONFIG_PATH = os.path.expanduser("~/.xsoft/paramsx_config.py")

# Ruta de la plantilla que se copia con 'paramsx configure'
PLANTILLA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paramsx_config.py"
)

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


# La configuración a partir de los nombres definidos en el fichero del usuario (un dict
# nombre -> valor). Lo usan la terminal, que ejecuta el fichero, y la web, que lo lee
# como datos: así las dos rellenan los valores por defecto igual.
def config_desde_valores(valores):
    if not isinstance(valores.get("configuraciones"), dict):
        raise ValueError("Falta el diccionario 'configuraciones'.")

    config = dict(valores["configuraciones"])
    # Todo lo que va fuera de 'configuraciones' es opcional en el fichero del usuario:
    # si no está, se usa el valor de la plantilla que trae el paquete.
    # 'naming' es el nombre que tuvo 'perfiles' en la 2.2.0
    config["perfiles"] = dict(
        valores.get("perfiles", valores.get("naming", plantilla_config.perfiles))
    )
    # 'abac' es el nombre antiguo (2.0/2.1) de 'tags_activas': se sigue aceptando.
    config["tags_activas"] = bool(
        valores.get("tags_activas", valores.get("abac", plantilla_config.tags_activas))
    )
    config["obligatorias_vacias"] = bool(
        valores.get("obligatorias_vacias", plantilla_config.obligatorias_vacias)
    )
    config["tags_obligatorias"] = list(
        valores.get("tags_obligatorias", plantilla_config.tags_obligatorias)
    )
    config["fichero_por_ruta"] = bool(
        valores.get("fichero_por_ruta", plantilla_config.fichero_por_ruta)
    )
    config["forzar_securestring"] = bool(
        valores.get("forzar_securestring", plantilla_config.forzar_securestring)
    )
    # Si no se declara, los parámetros nuevos usan el primer perfil definido
    # ('convencion_nuevos' es el nombre que tuvo en la 2.2.0)
    primer_perfil = next(iter(config["perfiles"]), None)
    config["perfil_nuevos"] = (
        valores.get("perfil_nuevos")
        or valores.get("convencion_nuevos")
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


# ---------------------------------------------------------------------------------------
# Leer y escribir el fichero como DATOS (lo usa la web: nunca ejecuta el fichero)
# ---------------------------------------------------------------------------------------

class ConfigNoLegible(ValueError):
    """El fichero tiene algo que no es un literal (un import, una variable...) y no se
    puede leer ni reescribir sin ejecutarlo."""


# Las asignaciones de primer nivel del fichero (nombre = literal). Lo que no sea un
# literal de Python se lista aparte: con eso la web no se arriesga a reescribirlo.
def leer_asignaciones(texto):
    try:
        arbol = ast.parse(texto or "")
    except SyntaxError as e:
        raise ConfigNoLegible(f"Error de sintaxis en la línea {e.lineno}: {e.msg}.") from None

    valores, no_literales = {}, []
    for nodo in arbol.body:
        if (isinstance(nodo, ast.Assign) and len(nodo.targets) == 1
                and isinstance(nodo.targets[0], ast.Name)):
            nombre = nodo.targets[0].id
            try:
                valores[nombre] = ast.literal_eval(nodo.value)
            except ValueError:
                no_literales.append(nombre)
    return valores, no_literales


# La configuración del fichero, leída sin ejecutarlo. Devuelve el mismo dict que
# config_desde_valores (sin normalizar, para no perder los avisos de validate_config).
def cargar_config_literal(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as f:
        valores, no_literales = leer_asignaciones(f.read())
    relevantes = set(CLAVES_OPCIONALES) | set(NOMBRES_ANTIGUOS) | {"configuraciones"}
    problemas = [n for n in no_literales if n in relevantes]
    if problemas:
        raise ConfigNoLegible(
            f"{', '.join(problemas)} no se puede leer como datos (usa variables, imports o "
            "llamadas). La web no ejecuta el fichero: déjalo con valores literales."
        )
    return config_desde_valores(valores)


# La configuración por defecto (la plantilla), para quien aún no tiene fichero
def config_plantilla():
    with open(PLANTILLA_PATH, "r", encoding="utf-8") as f:
        valores, _ = leer_asignaciones(f.read())
    return config_desde_valores(valores)


def _literal(valor):
    if isinstance(valor, str):
        return json.dumps(valor, ensure_ascii=False)
    if isinstance(valor, bool) or valor is None:
        return repr(valor)
    if isinstance(valor, (int, float)):
        return repr(valor)
    if isinstance(valor, (list, tuple)):
        return "[" + ", ".join(_literal(v) for v in valor) + "]"
    if isinstance(valor, dict):
        return "{" + ", ".join(f"{_literal(k)}: {_literal(v)}" for k, v in valor.items()) + "}"
    raise TypeError(f"No se puede escribir {type(valor).__name__} en la configuración.")


def _bloque_dict(nombre, valor, comentario=None):
    lineas = [f"{nombre} = {{"]
    for clave, v in valor.items():
        linea = f"    {_literal(clave)}: {_literal(v)},"
        if comentario:
            nota = comentario(clave, v)
            if nota:
                linea += f"  # {nota}"
        lineas.append(linea)
    lineas.append("}")
    return "\n".join(lineas)


# Las asignaciones nuevas, escritas como Python legible (una entrada por línea)
def _bloques(config, configuraciones_previas):
    perfiles = config["perfiles"]
    entornos = config["entornos"]

    def ruta_ejemplo(entrada):
        perfil = perfiles.get(entrada.get("perfil"))
        if not perfil or not entornos:
            return None
        try:
            return "-> " + build_full_path(entrada["path"], perfil, str(entornos[0]).lower())
        except ValueError:
            return None

    lista = ["["]
    for entrada in config["parameter_list"]:
        linea = f"        {_literal(entrada)},"
        nota = ruta_ejemplo(entrada)
        lista.append(linea + (f"  # {nota}" if nota else ""))
    lista.append("    ]")

    # Las claves de 'configuraciones' que la web no gestiona se conservan tal cual
    configuraciones = dict(configuraciones_previas or {})
    for clave in ("profile_name", "region_name", "entornos", "parameter_list"):
        configuraciones.pop(clave, None)
    lineas_conf = [
        "configuraciones = {",
        f'    "profile_name": {_literal(config["profile_name"])},  # perfil de ~/.aws/credentials',
        f'    "region_name": {_literal(config["region_name"])},  # región de AWS',
        f'    "entornos": {_literal(list(entornos))},  # SIEMPRE en minúscula',
        '    "parameter_list": ' + "\n".join(lista) + ",",
    ]
    lineas_conf += [f"    {_literal(k)}: {_literal(v)}," for k, v in configuraciones.items()]
    lineas_conf.append("}")

    tags = ["tags_obligatorias = ["] + [f"    {_literal(t)}," for t in config["tags_obligatorias"]] + ["]"]

    return {
        "perfiles": _bloque_dict("perfiles", perfiles),
        "configuraciones": "\n".join(lineas_conf),
        "perfil_nuevos": f"perfil_nuevos = {_literal(config['perfil_nuevos'])}",
        "fichero_por_ruta": f"fichero_por_ruta = {_literal(bool(config.get('fichero_por_ruta', False)))}",
        "forzar_securestring": f"forzar_securestring = {_literal(bool(config['forzar_securestring']))}",
        "tags_activas": f"tags_activas = {_literal(bool(config['tags_activas']))}",
        "obligatorias_vacias": f"obligatorias_vacias = {_literal(bool(config['obligatorias_vacias']))}",
        "tags_obligatorias": "\n".join(tags),
    }


# Reescribir el fichero con la configuración nueva conservando todo lo demás: los
# comentarios de fuera de cada asignación se quedan donde estaban y solo se sustituyen
# las asignaciones. Los nombres antiguos (naming, abac...) se cambian por los actuales.
# Si el fichero no existe, se parte de la plantilla comentada.
def texto_config(config, texto_actual):
    arbol = ast.parse(texto_actual)
    valores, _ = leer_asignaciones(texto_actual)
    bloques = _bloques(config, valores.get("configuraciones"))
    lineas = texto_actual.splitlines(keepends=True)

    # (inicio, fin, nombre_actual) de cada asignación que se sustituye, en orden inverso
    tramos = []
    for nodo in arbol.body:
        if not (isinstance(nodo, ast.Assign) and len(nodo.targets) == 1
                and isinstance(nodo.targets[0], ast.Name)):
            continue
        nombre = NOMBRES_ANTIGUOS.get(nodo.targets[0].id, nodo.targets[0].id)
        if nombre in bloques:
            tramos.append((nodo.lineno, nodo.end_lineno, nodo.end_col_offset, nombre))

    escritos = set()
    for inicio, fin, col_fin, nombre in sorted(tramos, reverse=True):
        # Un comentario detrás de la asignación, en su última línea, se conserva
        ultima = lineas[fin - 1].encode("utf-8")
        resto = ultima[col_fin:].decode("utf-8").rstrip("\n")
        cola = f"  {resto.strip()}" if resto.strip().startswith("#") else ""
        # Si un nombre aparece dos veces (el nuevo y el antiguo), solo se escribe una
        sustituto = "" if nombre in escritos else bloques[nombre] + cola + "\n"
        escritos.add(nombre)
        lineas[inicio - 1:fin] = [sustituto]

    texto = "".join(lineas)
    faltan = [n for n in bloques if n not in escritos]
    if faltan:
        texto = texto.rstrip("\n") + "\n\n## Añadido desde paramsx web\n"
        texto += "\n".join(bloques[n] for n in faltan) + "\n"
    return texto


# Guardar la configuración en disco. Antes de escribir se comprueba que lo que se va a
# escribir se vuelve a leer exactamente igual; el fichero anterior queda como .bak.
def guardar_config(config, path=CONFIG_PATH):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            actual = f.read()
    else:
        with open(PLANTILLA_PATH, "r", encoding="utf-8") as f:
            actual = f.read()

    texto = texto_config(config, actual)
    valores, no_literales = leer_asignaciones(texto)
    releido = config_desde_valores(valores)
    for clave in ("profile_name", "region_name", "entornos", "parameter_list", "perfiles",
                  "perfil_nuevos", "forzar_securestring", "tags_activas",
                  "obligatorias_vacias", "tags_obligatorias"):
        if releido.get(clave) != config.get(clave):
            raise ValueError(f"No se ha guardado: '{clave}' no se releía igual.")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path + ".bak", "w", encoding="utf-8") as f:
            f.write(actual)
    temporal = path + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        f.write(texto)
    os.replace(temporal, path)
    return texto
