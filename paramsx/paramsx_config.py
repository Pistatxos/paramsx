## Configuraciones ParamsX

configuraciones = {
    "profile_name": "default",           # Perfil de ~/.aws/credentials
    "region_name": "eu-south-2",         # Región de AWS
    "entornos": ['dev', 'pre', 'prod'],  # SIEMPRE en minúscula, es la lista canónica única
    "parameter_list": [
        # convencion "min" -> el entorno (minúscula) se añade al PRINCIPIO de la ruta:
        #     "/rds"     + dev -> /dev/rds
        # convencion "max" -> el entorno (mayúscula) se inserta TRAS EL PRIMER SEGMENTO:
        #     "/API/STA" + dev -> /API/DEV/STA
        #     "/EMAIL"   + dev -> /EMAIL/DEV
        {"path": "/common", "convencion": "min"},
        {"path": "/rds", "convencion": "min"},
        {"path": "/api", "convencion": "min"},
        {"path": "/EMAIL", "convencion": "max"},
        {"path": "/API/STA", "convencion": "max"},
    ]
}

# Control de acceso ABAC:
#   True  -> las tags se leen de AWS, se muestran/editan en el fichero exportado y es
#            obligatorio que todas las tags de 'tags_obligatorias' tengan valor para subir.
#   False -> las tags no aparecen en el fichero exportado (comportamiento legacy, sin tags).
abac = True

# ¿Se pueden dejar vacías las tags obligatorias?
#   False -> validación bloqueante: si a un parámetro le falta alguna de 'tags_obligatorias'
#            no se sube (ni su valor ni sus tags).
#   True  -> se permiten vacías: el parámetro se sube igualmente y las tags sin valor
#            simplemente NO se crean en AWS (no se suben como etiquetas vacías).
obligatorias_vacias = False

# Estas tags sostienen el control de acceso ABAC vía IAM en toda la cuenta AWS.
# La lista es ampliable, pero estas 8 son el mínimo por defecto.
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
