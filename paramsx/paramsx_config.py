## Configuraciones ParamsX

# --- Perfiles de naming -------------------------------------------------------------
# Un perfil dice CÓMO se construye la ruta real en AWS a partir de la ruta que declaras
# en 'parameter_list' y del entorno que eliges en el menú. Los nombres son tuyos: define
# solo los que uses y llámalos como quieras. Un perfil tiene tres campos:
#
#   campo             | valores                                  | qué decide
#   ------------------+------------------------------------------+---------------------------
#   posicion_entorno  | inicio | final | mixto | ninguno          | dónde va el entorno
#   case_entorno      | lower | upper | capitalize                | cómo se escribe el entorno
#   case_ruta         | lower | upper | capitalize | ninguno      | case de la ruta AL CREAR
#
# posicion_entorno -> dónde se coloca el entorno (ejemplos con el entorno 'dev'):
#
#   valor    | ruta declarada  | ruta real en AWS
#   ---------+-----------------+--------------------------------------------------------
#   inicio   | /rds            | /dev/rds
#   final    | /API/STA        | /API/STA/DEV
#   mixto    | /API/*/STA      | /API/DEV/STA    el '*' marca el sitio; uno y como segmento
#   ninguno  | /api/sta/auth   | /api/sta/auth   una cuenta AWS por entorno; case_entorno da igual
#
# case_entorno -> cómo se escribe ese entorno en la ruta:
#
#   valor       | 'dev' se escribe | ruta real de /API/STA con posicion_entorno=final
#   ------------+------------------+------------------------------------------------
#   lower       | dev              | /API/STA/dev
#   upper       | DEV              | /API/STA/DEV
#   capitalize  | Dev              | /API/STA/Dev
#
# case_ruta -> a qué case se fuerza la ruta que TÚ escribes al CREAR un parámetro
# (opción 4 del menú). No afecta a leer ni a editar: lo que ya existe en AWS se
# respeta siempre tal cual esté.
#
#   valor       | si escribes /API/MULTIAPI/Token, se crea
#   ------------+-----------------------------------------
#   lower       | /api/multiapi/token
#   upper       | /API/MULTIAPI/TOKEN
#   capitalize  | /Api/Multiapi/Token
#   ninguno     | /API/MULTIAPI/Token
#
# Combina los tres campos como necesites: no hay una lista cerrada de perfiles. En el
# README tienes más ejemplos.

naming = {
    "min": {"posicion_entorno": "inicio", "case_entorno": "lower", "case_ruta": "lower"},
    "max": {"posicion_entorno": "final", "case_entorno": "upper", "case_ruta": "ninguno"},
    "mixto_max": {"posicion_entorno": "mixto", "case_entorno": "upper", "case_ruta": "ninguno"},
    # Crea los tuyos combinando los valores de la tabla, por ejemplo:
    # "sin_entorno": {"posicion_entorno": "ninguno", "case_entorno": "lower", "case_ruta": "ninguno"},
}

configuraciones = {
    "profile_name": "default",           # Cambiar por el nombre de tu perfil en ~/.aws/credentials
    "region_name": "eu-south-2",         # Cambiar por tu región de AWS
    "entornos": ['dev', 'pre', 'prod'],  # SIEMPRE en minúscula, es la lista canónica única
    "parameter_list": [
        {"path": "/common", "convencion": "min"},      # -> /dev/common
        {"path": "/rds", "convencion": "min"},         # -> /dev/rds
        {"path": "/EMAIL", "convencion": "max"},       # -> /EMAIL/DEV
        {"path": "/API/STA", "convencion": "max"},     # -> /API/STA/DEV
        # Con 'mixto' acotas por debajo del entorno: esto lee solo stan_ai, en vez de
        # todo lo que cuelga de /API/MULTIAPI/DEV
        {"path": "/API/MULTIAPI/*/stan_ai", "convencion": "mixto_max"},  # -> /API/MULTIAPI/DEV/stan_ai
    ]
}

# Perfil de naming que se usa al crear un parámetro nuevo (opción 4 del menú).
# Si no lo defines, se usa el primer perfil de 'naming'.
convencion_nuevos = "min"

# ¿El nombre del fichero exportado incluye la ruta leída?
#   False -> parameters_dev.py            (comportamiento de siempre)
#   True  -> parameters_dev__API_STA__max.py  (uno por entrada y entorno: lleva el
#            entorno, la ruta y el perfil, porque dos entradas pueden compartir ruta)
# Ponlo en True si sueles leer varias rutas del mismo entorno y no quieres que la
# segunda lectura te machaque el fichero de la primera.
fichero_por_ruta = False


## Configuraciones Tags

# Gestionar las tags de los parámetros: leerlas de AWS, exponerlas en el fichero
# exportado para editarlas y validar las obligatorias al cargar.
#   True  -> las tags viajan en el fichero y se validan.
#   False -> no aparecen tags en el fichero y no se valida nada.
# En cuentas cuyo control de acceso va por tags (ABAC vía IAM) esto debe estar en True.
tags_activas = True

# Solo aplica si tags_activas = True.
#   False -> validación bloqueante: si a un parámetro le falta alguna tag obligatoria
#            no se sube (ni su valor ni sus tags).
#   True  -> se permiten vacías: el parámetro se sube igualmente y las tags sin valor
#            simplemente NO se crean en AWS (no se suben como etiquetas vacías).
obligatorias_vacias = False

# Tags que se exigen en cada parámetro cuando tags_activas = True. La lista es libre:
# estas 8 son las que sostienen el control de acceso ABAC vía IAM de nuestra cuenta.
tags_obligatorias = [
    "Application",
    "Environment",
    "Owner",
    "Project",
    "Product",
    "Service",
    "Component",
    "ManagedBy",
]
