# Valores admitidos en un perfil
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


# Construir la ruta completa aplicando el perfil de la entrada.
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


# El case con el que está escrito un entorno en una ruta real: DEV -> upper, Dev -> capitalize
def detectar_case(escrito):
    if escrito == escrito.lower():
        return "lower"
    if escrito == escrito.upper():
        return "upper"
    return "capitalize"


# A partir de una carpeta real de AWS, la entrada de parameter_list que la describe.
# Busca un segmento que sea uno de los entornos (sin distinguir mayúsculas): el primero
# -> inicio, el último -> final, en medio -> mixto con '*' en su sitio, ninguno -> ninguno.
# Usa un perfil existente que encaje y, si no hay, propone uno nuevo (inicio_lower...).
# Devuelve (entrada, perfil_nuevo) donde perfil_nuevo es None o (nombre, definición).
def grupo_desde_carpeta(carpeta, entornos, perfiles):
    segmentos = [s for s in str(carpeta).strip("/").split("/") if s]
    entornos = {str(e).lower() for e in entornos}
    idx = next((i for i, s in enumerate(segmentos) if s.lower() in entornos), -1)

    if idx < 0:
        posicion, case_entorno, plantilla = "ninguno", "lower", segmentos
    else:
        case_entorno = detectar_case(segmentos[idx])
        if idx == 0:
            posicion = "inicio"
        elif idx == len(segmentos) - 1:
            posicion = "final"
        else:
            posicion = "mixto"
        if posicion == "mixto":
            plantilla = [MARCADOR_ENTORNO if i == idx else s for i, s in enumerate(segmentos)]
        else:
            plantilla = [s for i, s in enumerate(segmentos) if i != idx]

    if not plantilla:
        raise ValueError(
            f"{carpeta} es solo el entorno: elige una carpeta que tenga algo más en la ruta."
        )

    path = "/" + "/".join(plantilla)
    nombre_perfil = next(
        (n for n, p in perfiles.items()
         if p.get("posicion_entorno") == posicion
         and (posicion == "ninguno" or p.get("case_entorno", "lower") == case_entorno)),
        None,
    )
    perfil_nuevo = None
    if nombre_perfil is None:
        base = posicion if posicion == "ninguno" else f"{posicion}_{case_entorno}"
        nombre_perfil, n = base, 2
        while nombre_perfil in perfiles:
            nombre_perfil, n = f"{base}{n}", n + 1
        perfil_nuevo = (nombre_perfil, {
            "posicion_entorno": posicion, "case_entorno": case_entorno, "case_ruta": "ninguno",
        })

    nombre = [s for s in plantilla if s != MARCADOR_ENTORNO][-1]
    return {"nombre": nombre, "path": path, "perfil": nombre_perfil}, perfil_nuevo
