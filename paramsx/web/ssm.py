"""SSM Parameter Store para la versión web: cargar una ruta, revisar los cambios contra AWS en
ese momento, aplicarlos e historial.

- Todo va con el rol de IAM del perfil elegido: lo que no puede leer o descifrar sale como
  «sin permiso» (bloqueado), no como error, para poder trabajar con lo que sí puede.
- Los valores nunca se escriben a disco ni a logs: se devuelven al navegador y nada más.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

TIPOS = ("String", "StringList", "SecureString")
MAX_STANDARD, MAX_ADVANCED = 4096, 8192
MAX_LISTADO = 2000  # parámetros como mucho por carga (el resto se avisa)
MAX_CONTIENEN = 200  # al buscar por un trozo del nombre (cuando la ruta no existe)
KMS_DEFECTO = ("alias/aws/ssm", "")
NOMBRE = re.compile(r"^[A-Za-z0-9_.\-/]{1,2048}$")
REINTENTOS_TOO_MANY_UPDATES = 2


class ParametrosError(Exception):
    pass


def cliente(session, region):
    return session.client(
        "ssm", region_name=region,
        config=Config(retries={"max_attempts": 10, "mode": "adaptive"}),
    )


def codigo(exc):
    return exc.response.get("Error", {}).get("Code", "") if isinstance(exc, ClientError) else ""


def _es_kms(exc):
    texto = str(exc).lower()
    return codigo(exc) in ("InvalidKeyId", "KMSAccessDeniedException") or "kms" in texto


def denegado(exc):
    """Sin permiso de IAM o sin poder descifrar con KMS: se muestra como 🔒, no como error."""
    return codigo(exc) in ("AccessDeniedException", "AccessDenied", "UnauthorizedOperation") or (
        isinstance(exc, ClientError) and _es_kms(exc)
    )


def motivo(exc):
    """Mensaje claro de un error de AWS."""
    c = codigo(exc)
    if denegado(exc):
        return "Sin permiso para descifrarlo (KMS)." if _es_kms(exc) else "Tu rol de IAM no tiene permiso."
    mensaje = exc.response.get("Error", {}).get("Message", "") if isinstance(exc, ClientError) else str(exc)
    return {
        "ParameterAlreadyExists": "Ya existe un parámetro con ese nombre.",
        "ParameterNotFound": "Ya no existe en AWS.",
        "ParameterLimitExceeded": "Se ha llegado al límite de parámetros de la cuenta.",
        "ParameterMaxVersionLimitExceeded": "El parámetro tiene 100 versiones y la más antigua "
                                            "tiene etiqueta de versión: quítasela en la consola.",
        "TooManyUpdates": "Demasiados cambios seguidos en el mismo parámetro: vuelve a "
                          "intentarlo en unos segundos.",
        "ValidationException": f"AWS no lo acepta: {mensaje}",
        "HierarchyLevelLimitExceededException": "La ruta tiene más de 15 niveles.",
        "HierarchyTypeMismatchException": "No se puede cambiar el tipo de un parámetro de "
                                          "String a SecureString (o al revés) en esa jerarquía.",
        "UnsupportedParameterType": "Tipo de parámetro no admitido.",
    }.get(c) or f"{c or type(exc).__name__}: {mensaje}"


# ---------------------------------------------------------------- lectura

def _meta(p):
    fecha = p.get("LastModifiedDate")
    return {
        "type": p.get("Type"), "key_id": p.get("KeyId", ""), "tier": p.get("Tier", "Standard"),
        "version": p.get("Version"), "description": p.get("Description", ""),
        "modified": fecha.isoformat() if fecha else "", "user": p.get("LastModifiedUser", ""),
        "data_type": p.get("DataType", "text"),
    }


def describir(ssm, ruta, nombres=None, contiene=""):
    """{nombre: metadatos} (sin valores) de una ruta (recursivo), de unos nombres concretos o de los
    que llevan un texto (lo filtra AWS, distingue mayúsculas)."""
    if contiene:
        return _describir_filtro(ssm, [{"Key": "Name", "Option": "Contains", "Values": [contiene]}])
    if nombres is not None:
        out = {}
        # El filtro Name admite hasta 50 valores
        for i in range(0, len(nombres), 50):
            out.update(_describir_filtro(ssm, [{"Key": "Name", "Option": "Equals",
                                                "Values": nombres[i:i + 50]}]))
        return out
    ruta = ruta.rstrip("/")
    filtros = [{"Key": "Path", "Option": "Recursive", "Values": [ruta]}] if ruta else []
    return _describir_filtro(ssm, filtros)


def _describir_filtro(ssm, filtros):
    out, token = {}, None
    while True:
        kw = {"MaxResults": 50}
        if filtros:
            kw["ParameterFilters"] = filtros
        if token:
            kw["NextToken"] = token
        r = ssm.describe_parameters(**kw)
        for p in r.get("Parameters", []):
            out[p["Name"]] = _meta(p)
        token = r.get("NextToken")
        if not token or len(out) >= MAX_LISTADO:
            return out


def _valor(p):
    return {"value": p.get("Value", ""), "type": p.get("Type"), "version": p.get("Version")}


def _valores_por_ruta(ssm, ruta):
    out, token = {}, None
    while True:
        kw = {"Path": ruta.rstrip("/") or "/", "Recursive": True, "WithDecryption": True,
              "MaxResults": 10}
        if token:
            kw["NextToken"] = token
        r = ssm.get_parameters_by_path(**kw)
        for p in r.get("Parameters", []):
            out[p["Name"]] = _valor(p)
        token = r.get("NextToken")
        if not token or len(out) >= MAX_LISTADO:
            return out


def valores_por_nombre(ssm, nombres):
    """{nombre: {'value', 'type', 'version'} | {'bloqueado': motivo} | {'no_existe': True}}.
    De 10 en 10 y, si un lote no se deja, uno a uno: así se sabe exactamente qué parámetros
    no puede leer el rol."""
    out = {}
    for i in range(0, len(nombres), 10):
        lote = nombres[i:i + 10]
        try:
            r = ssm.get_parameters(Names=lote, WithDecryption=True)
            for p in r.get("Parameters", []):
                out[p["Name"]] = _valor(p)
            for n in r.get("InvalidParameters", []):
                out[n] = {"no_existe": True}
        except ClientError as exc:
            if not denegado(exc):
                raise
            for n in lote:
                try:
                    out[n] = _valor(ssm.get_parameter(Name=n, WithDecryption=True)["Parameter"])
                except ClientError as e:
                    out[n] = {"no_existe": True} if codigo(e) == "ParameterNotFound" else {"bloqueado": motivo(e)}
    return out


def etiquetas(ssm, nombres):
    """{nombre: {clave: valor} | None (sin permiso)}; en paralelo con pocos hilos, porque AWS
    limita mucho estas llamadas."""
    def una(n):
        try:
            r = ssm.list_tags_for_resource(ResourceType="Parameter", ResourceId=n)
        except ClientError:
            return n, None
        return n, {t["Key"]: t["Value"] for t in r.get("TagList", []) if not t["Key"].startswith("aws:")}

    if not nombres:
        return {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(pool.map(una, nombres))


def _uno(ssm, nombre):
    """Lo escrito en «Ruta» es un parámetro, no una carpeta (o uno sin «/», que no está en
    ninguna): (meta, valores) o None si no existe."""
    try:
        meta = describir(ssm, "", nombres=[nombre])
    except ClientError as exc:
        if not denegado(exc):
            raise ParametrosError(motivo(exc)) from None
        meta = None
    try:
        valores = valores_por_nombre(ssm, [nombre])
    except ClientError as exc:
        raise ParametrosError(motivo(exc)) from None
    if not meta and valores.get(nombre, {}).get("no_existe"):
        return None
    if meta and len(meta) == 1 and nombre not in meta and nombre in valores:  # GetParameters repite el nombre tal como se pidió
        valores = {next(iter(meta)): valores[nombre]}
    return meta, valores


def cargar(ssm, ruta):
    """Los parámetros de una ruta (recursivo) con valor, metadatos y etiquetas. Lo que el rol no
    puede leer va con `bloqueado`. ParametrosError si no puede ni listar ni leer la ruta. Si no hay
    nada debajo de la ruta: el parámetro con ese nombre (también sin «/», p. ej. «MiParametro») y,
    si tampoco, los que llevan ese texto en el nombre («/common/rds/x» encuentra
    «/prod/common/rds/x», «/dev/common/rds/x»…)."""
    ruta = "/" + ruta.strip().strip("/") if ruta.strip().strip("/") else "/"
    avisos = []
    try:
        meta = describir(ssm, ruta)
    except ClientError as exc:
        if not denegado(exc):
            raise ParametrosError(motivo(exc)) from None
        meta = None
        avisos.append("Tu rol no puede listar parámetros (ssm:DescribeParameters): "
                      "faltan descripción, tier y último cambio.")

    try:
        valores = _valores_por_ruta(ssm, ruta)
        # Los que se listan pero no vienen con valor (p. ej. uno que no se puede descifrar)
        faltan = [n for n in (meta or {}) if n not in valores]
        if faltan:
            valores.update(valores_por_nombre(ssm, faltan))
    except ClientError as exc:
        if not denegado(exc):
            raise ParametrosError(motivo(exc)) from None
        if meta is None:
            raise ParametrosError(
                f"Tu rol de IAM no puede listar ni leer parámetros en {ruta}."
            ) from None
        # La ruta entera no se deja (o un descifrado tumba la página): uno a uno
        valores = valores_por_nombre(ssm, sorted(meta))

    if not meta and not valores and ruta != "/":
        # el nombre exacto; sin carpeta, AWS trata «/Nombre» y «Nombre» como el mismo: primero sin
        # la barra (su nombre de verdad)
        uno = ("/" not in ruta[1:] and _uno(ssm, ruta[1:])) or _uno(ssm, ruta)
        if uno:
            meta, valores = uno
            if ruta not in (meta or valores):
                ruta = ruta[1:]
        else:
            meta, valores, aviso = _contienen(ssm, ruta[1:])
            if aviso:
                avisos.append(aviso)
            if meta:  # para que la pantalla diga «Buscado …» en vez de la ruta
                return {**_montar(ssm, ruta, meta, valores, avisos), "buscado": ruta[1:]}
    return _montar(ssm, ruta, meta, valores, avisos)


def _contienen(ssm, texto):
    """(meta, valores, aviso) de los parámetros con `texto` en el nombre (como mucho MAX_CONTIENEN)."""
    try:
        meta = describir(ssm, "", contiene=texto)
    except ClientError as exc:
        if not denegado(exc):
            raise ParametrosError(motivo(exc)) from None
        return {}, {}, ""
    if not meta:
        return {}, {}, ""
    nombres = sorted(meta)[:MAX_CONTIENEN]
    meta = {n: meta[n] for n in nombres}
    try:
        valores = valores_por_nombre(ssm, nombres)
    except ClientError as exc:
        raise ParametrosError(motivo(exc)) from None
    aviso = f"Hay más: se muestran los {MAX_CONTIENEN} primeros, acota." if len(nombres) >= MAX_CONTIENEN else ""
    return meta, valores, aviso


def _montar(ssm, ruta, meta, valores, avisos):
    nombres = sorted(n for n in set(meta or {}) | set(valores)
                     if not valores.get(n, {}).get("no_existe"))
    legibles = [n for n in nombres if "bloqueado" not in valores.get(n, {})]
    tags = etiquetas(ssm, legibles)

    parametros = []
    for n in nombres:
        m, v = (meta or {}).get(n, {}), valores.get(n, {})
        parametros.append({
            "name": n, "type": v.get("type") or m.get("type"), "value": v.get("value"),
            "bloqueado": v.get("bloqueado", ""), "version": v.get("version") or m.get("version"),
            "description": m.get("description", ""), "tier": m.get("tier", "Standard"),
            "kms_propia": m.get("key_id", "") not in KMS_DEFECTO, "modified": m.get("modified", ""),
            "user": m.get("user", ""), "tags": tags.get(n),
            "descripcion_legible": meta is not None,
        })
    if len(nombres) >= MAX_LISTADO:
        avisos.append(f"Hay más de {MAX_LISTADO} parámetros: se muestran {MAX_LISTADO}, acota la ruta.")
    return {"ruta": ruta, "parametros": parametros, "avisos": avisos}


def explorar(ssm, prefijo="/", contiene=""):
    """Nombres (sin valores) para el árbol de «Explorar» y la búsqueda de Ajustes. Con `contiene`,
    solo los que llevan ese texto: así se encuentran también cuando hay más de MAX_LISTADO."""
    try:
        meta = describir(ssm, prefijo or "/", contiene=contiene)
    except ClientError as exc:
        raise ParametrosError(
            "Tu rol de IAM no puede listar parámetros (ssm:DescribeParameters)."
            if denegado(exc) else motivo(exc)
        ) from None
    return {"nombres": sorted(meta), "limitado": len(meta) >= MAX_LISTADO}


def historial(ssm, nombre):
    """Versiones de AWS (hasta 100), de la más nueva a la más antigua, con su valor."""
    versiones, token = [], None
    try:
        while True:
            kw = {"Name": nombre, "WithDecryption": True, "MaxResults": 50}
            if token:
                kw["NextToken"] = token
            r = ssm.get_parameter_history(**kw)
            for p in r.get("Parameters", []):
                fecha = p.get("LastModifiedDate")
                versiones.append({
                    "version": p.get("Version"), "value": p.get("Value", ""), "type": p.get("Type"),
                    "description": p.get("Description", ""),
                    "modified": fecha.isoformat() if fecha else "",
                    "user": p.get("LastModifiedUser", ""), "labels": p.get("Labels", []),
                })
            token = r.get("NextToken")
            if not token:
                break
    except ClientError as exc:
        raise ParametrosError(motivo(exc)) from None
    return sorted(versiones, key=lambda v: v["version"] or 0, reverse=True)[:100]


# ---------------------------------------------------------------- revisar y aplicar

def validar_item(it, cfg):
    """Errores de un parámetro editado, antes de ir a AWS."""
    errores = []
    nombre = it.get("name") or ""
    segmentos = nombre.strip("/").split("/")
    if (not nombre.startswith("/") or not NOMBRE.match(nombre) or nombre.endswith("/")
            or "" in segmentos):
        errores.append("Nombre no válido: empieza por / y solo lleva letras, números y _ . - / "
                       "(sin acabar en / ni //).")
    if nombre.lower().lstrip("/").startswith(("aws", "ssm")):
        errores.append("Un nombre no puede empezar por «aws» ni «ssm».")
    if nombre.count("/") > 15:
        errores.append("Más de 15 niveles en la ruta.")
    if it.get("accion") == "borrar":
        return errores

    valor = it.get("value")
    if not isinstance(valor, str) or not valor:
        errores.append("El valor no puede estar vacío.")
    elif len(valor.encode("utf-8")) > MAX_ADVANCED:
        errores.append(f"El valor pasa de {MAX_ADVANCED // 1024} KB, el máximo de SSM.")
    if it.get("type") not in TIPOS:
        errores.append("Tipo no válido.")
    if len(it.get("description") or "") > 1024:
        errores.append("La descripción pasa de 1024 caracteres.")

    tags = it.get("tags")
    if tags is not None:
        if not isinstance(tags, dict) or len(tags) > 50:
            errores.append("Etiquetas no válidas (50 como mucho).")
        else:
            for k, v in tags.items():
                if not k or len(k) > 128 or len(str(v)) > 256 or k.lower().startswith("aws:"):
                    errores.append(f"Etiqueta «{k}» no válida (clave hasta 128, valor hasta 256, "
                                   "sin «aws:»).")
    if it.get("accion") == "nuevo" and cfg.get("tags_activas") and not cfg.get("obligatorias_vacias"):
        faltan = [k for k in cfg.get("tags_obligatorias", []) if not str((tags or {}).get(k, "")).strip()]
        if faltan:
            errores.append(f"Faltan etiquetas obligatorias: {', '.join(faltan)}.")
    return errores


def _revisar(ssm, items, cfg):
    """El plan y lo leído de AWS para hacerlo: (filas, meta). Se lee AWS en este momento."""
    nombres = sorted({it["name"] for it in items if isinstance(it, dict) and it.get("name")})
    # De los renombrados también se lee el viejo (su clave KMS pasa al nuevo), aunque no se borre
    viejos = {it["de"] for it in items if it.get("accion") == "nuevo" and isinstance(it.get("de"), str) and it["de"]}
    try:
        meta = describir(ssm, "", sorted(set(nombres) | viejos)) if nombres else {}
    except ClientError as exc:
        if not denegado(exc):
            raise ParametrosError(motivo(exc)) from None
        meta = None
    vivos = valores_por_nombre(ssm, nombres) if nombres else {}
    existentes = [n for n in nombres if "value" in vivos.get(n, {}) or n in (meta or {})]
    tags_vivas = etiquetas(ssm, existentes)
    # Las etiquetas de los viejos de un renombrado: None si el rol no las puede leer (no se sabe cuáles copiar)
    tags_viejos = {**tags_vivas, **etiquetas(ssm, sorted(viejos - set(tags_vivas)))}

    filas = []
    for it in items:
        nombre, accion = it.get("name", ""), it.get("accion")
        v, m = vivos.get(nombre, {}), (meta or {}).get(nombre)
        existe = m is not None or "value" in v or "bloqueado" in v
        fila = {"name": nombre, "accion": accion, "errores": validar_item(it, cfg), "avisos": [],
                "cambios": []}
        tam = len((it.get("value") or "").encode("utf-8"))

        if accion == "nuevo":
            if existe:
                fila["errores"].append("Ya existe en AWS: recarga el grupo.")
            de = it.get("de")
            if isinstance(de, str) and de and tags_viejos.get(de, {}) is None \
                    and not vivos.get(de, {}).get("no_existe"):
                # Renombrar sin poder leerlas crearía el nuevo sin ellas y borraría el viejo: se perderían
                fila["errores"].append(f"No se pueden leer las etiquetas de {de} (falta el permiso ssm:ListTagsForResource): no se renombra para no perderlas.")
            fila["cambios"] = ["valor", "tipo"] + (["descripción"] if it.get("description") else []) \
                + (["etiquetas"] if any(str(x).strip() for x in (it.get("tags") or {}).values()) else [])
            if tam > MAX_STANDARD:
                fila["avisos"].append("Pasa de 4 KB: se crea en el tier Advanced "
                                      "(0,05 USD al mes; no se puede volver a Standard).")
        elif accion in ("editar", "borrar"):
            if not existe:
                fila["errores"].append("Ya no existe en AWS.")
            elif v.get("bloqueado"):
                fila["errores"].append(v["bloqueado"])
            elif it.get("version") and v.get("version") != it.get("version"):
                fila["conflicto"] = True
                fila["errores"].append(
                    f"Conflicto: alguien lo ha cambiado mientras tanto (versión {it.get('version')} "
                    f"→ {v.get('version')}). Recarga el grupo.")
            if accion == "editar" and not fila["errores"]:
                _comparar(fila, it, v, m, meta is not None, tags_vivas.get(nombre))
                if (m or {}).get("tier") == "Standard" and tam > MAX_STANDARD:
                    fila["avisos"].append("Pasa de 4 KB: tier Advanced (0,05 USD/mes, no se puede "
                                          "volver a Standard).")
                if not fila["cambios"]:
                    fila["errores"].append("Sin cambios respecto a lo que hay ahora en AWS.")
        else:
            fila["errores"].append("Acción no válida.")
        filas.append(fila)

    # Renombrar es crear el nuevo y borrar el viejo: si el nuevo no se puede crear, el viejo no se borra (se perdería)
    borrados = {f["name"]: f for f in filas if f["accion"] == "borrar"}
    for it, fila in zip(items, filas):
        viejo = borrados.get(it.get("de") or "") if it.get("accion") == "nuevo" else None
        if viejo and fila["errores"] and not viejo["errores"]:
            viejo["errores"].append(f"No se borra: su nuevo nombre ({fila['name']}) no se puede crear.")
    return filas, meta or {}


def _comparar(fila, it, vivo, meta, meta_legible, tags_antes):
    if it.get("value") != vivo.get("value"):
        fila["cambios"].append("valor")
        fila["antes"] = vivo.get("value")
    if it.get("type") != vivo.get("type"):
        fila["cambios"].append("tipo")
        if vivo.get("type") == "SecureString":
            fila["avisos"].append("Deja de ser SecureString: el valor quedará sin cifrar.")
    if meta_legible and (it.get("description") or "") != (meta or {}).get("description", ""):
        fila["cambios"].append("descripción")
    nuevas = it.get("tags")
    if nuevas is not None and tags_antes is not None:
        poner = {k: str(x) for k, x in nuevas.items() if str(x).strip() and tags_antes.get(k) != str(x)}
        quitar = [k for k in tags_antes if not str(nuevas.get(k, "")).strip()]
        if poner or quitar:
            fila["cambios"].append("etiquetas")
            fila["tags_poner"], fila["tags_quitar"] = poner, quitar
    if not meta_legible and {"valor", "tipo"} & set(fila["cambios"]):
        fila["avisos"].append("Tu rol no puede leer la descripción: al guardar el valor, AWS "
                              "puede dejarla vacía.")


def plan(ssm, items, cfg):
    """Qué se va a hacer con cada parámetro editado, comparado con AWS en este momento.
    `items`: [{name, accion (nuevo|editar|borrar), version (la cargada), value, description,
    type, tags}]. Lo que tenga errores no se aplicará."""
    filas, _ = _revisar(ssm, items, cfg)
    return filas


def _put(ssm, **kw):
    for intento in range(REINTENTOS_TOO_MANY_UPDATES + 1):
        try:
            return ssm.put_parameter(**kw)
        except ClientError as exc:
            if codigo(exc) != "TooManyUpdates" or intento == REINTENTOS_TOO_MANY_UPDATES:
                raise
            time.sleep(1.5 * (intento + 1))


def aplicar(ssm, items, cfg):
    """Aplica lo revisado. Se vuelve a comparar con AWS en el momento: lo que tenga errores
    (conflicto, sin permiso...) no se toca y el resto se aplica. Devuelve
    [{name, accion, ok, error, version, cambios}] sin valores."""
    filas, meta = _revisar(ssm, items, cfg)
    revisado = {f["name"]: f for f in filas}
    resultados, borrar, sin_sustituto = [], [], set()

    for it in items:
        nombre, accion = it.get("name", ""), it.get("accion")
        fila = revisado.get(nombre, {})
        res = {"name": nombre, "accion": accion, "ok": False, "error": "", "version": None,
               "cambios": fila.get("cambios", [])}
        if fila.get("errores"):
            res["error"] = " ".join(fila["errores"])
            resultados.append(res)
            continue
        if accion == "borrar":
            borrar.append(res)
            continue
        try:
            m = meta.get(it.get("de") or "", {}) if accion == "nuevo" else meta.get(nombre, {})
            res["version"] = _aplicar_uno(ssm, it, fila, m, accion)
            res["ok"] = True
        except (ClientError, BotoCoreError) as exc:
            res["error"] = motivo(exc)
            if accion == "nuevo" and it.get("de"):
                sin_sustituto.add(it["de"])
        resultados.append(res)

    # Su nuevo nombre no se pudo crear: el viejo se queda
    for b in [b for b in borrar if b["name"] in sin_sustituto]:
        b["error"] = "No se borra: su nuevo nombre no se pudo crear."
        borrar.remove(b)
        resultados.append(b)

    # Justo antes de borrar, otra vez la versión de cada uno (sin valores ni descifrar): si alguien lo ha cambiado desde
    # la revisión (también mientras se creaban los renombrados), no se borra. SSM no tiene «borrar solo si sigue en la
    # versión N»: entre esta lectura y el borrado queda una ventana de milisegundos que no se puede cerrar desde aquí.
    esperada = {it.get("name"): it.get("version") for it in items if it.get("accion") == "borrar" and it.get("version")}
    copia_de = {it.get("de"): it.get("name") for it in items if it.get("accion") == "nuevo" and it.get("de")}
    try:
        ahora = describir(ssm, "", [b["name"] for b in borrar]) if borrar else {}
    except (ClientError, BotoCoreError) as exc:
        if not denegado(exc):
            # Otro fallo (red, límite de llamadas...): sin comprobar no se borra, pero lo ya aplicado se devuelve
            for b in borrar:
                b["error"] = f"No se pudo comprobar la versión antes de borrar ({motivo(exc)}): no se borra."
            resultados += borrar
            return resultados
        ahora = None  # sin permiso para describir: se borra como antes (ya se comprobó al revisar)
    for b in [b for b in borrar if ahora is not None and b["name"] in ahora and b["name"] in esperada
              and ahora[b["name"]].get("version") != esperada[b["name"]]]:
        b["error"] = (f"Ha cambiado en AWS mientras se aplicaba (versión {esperada[b['name']]} → "
                      f"{ahora[b['name']].get('version')}): no se borra. "
                      + (f"Su copia «{copia_de[b['name']]}» se creó con el valor de antes: revisa cuál dejar."
                         if b["name"] in copia_de else "Recarga el grupo."))
        borrar.remove(b)
        resultados.append(b)

    # Borrados de 10 en 10 (el máximo de DeleteParameters)
    for i in range(0, len(borrar), 10):
        lote = borrar[i:i + 10]
        try:
            r = ssm.delete_parameters(Names=[b["name"] for b in lote])
            hechos, invalidos = set(r.get("DeletedParameters", [])), set(r.get("InvalidParameters", []))
            for b in lote:
                b["ok"] = b["name"] in hechos
                if not b["ok"]:
                    b["error"] = "Ya no existe en AWS." if b["name"] in invalidos else "AWS no lo borró."
        except ClientError as exc:
            for b in lote:
                b["error"] = motivo(exc)
        resultados += lote
    return resultados


def _aplicar_uno(ssm, it, fila, m, accion):
    valor = it["value"]
    grande = len(valor.encode("utf-8")) > MAX_STANDARD

    if accion == "nuevo":
        kw = {"Name": it["name"], "Value": valor, "Type": it["type"], "Overwrite": False}
        if it.get("description"):
            kw["Description"] = it["description"]
        tags = [{"Key": k, "Value": str(v)} for k, v in (it.get("tags") or {}).items() if str(v).strip()]
        if tags:
            kw["Tags"] = tags
        if grande:
            kw["Tier"] = "Advanced"
        # Renombrado (m es el viejo): se conserva su clave KMS propia en vez de la de por defecto
        if it["type"] == "SecureString" and m.get("key_id") and m["key_id"] not in KMS_DEFECTO:
            kw["KeyId"] = m["key_id"]
        return _put(ssm, **kw).get("Version")

    version = None
    if {"valor", "tipo", "descripción"} & set(fila["cambios"]):
        kw = {"Name": it["name"], "Value": valor, "Overwrite": True}
        # Overwrite reescribe la definición: la descripción va SIEMPRE (la nueva o la que había)
        if "descripción" in fila["cambios"]:
            kw["Description"] = it.get("description") or ""
        elif m:
            kw["Description"] = m.get("description", "")
        # El tipo solo si cambia: si no se manda, AWS conserva el que tenga
        if "tipo" in fila["cambios"]:
            kw["Type"] = it["type"]
        # Sin KeyId, AWS volvería a cifrar con la clave por defecto: la propia se conserva
        if it["type"] == "SecureString" and m.get("key_id") and m["key_id"] not in KMS_DEFECTO:
            kw["KeyId"] = m["key_id"]
        if m.get("tier") == "Advanced" or grande:
            kw["Tier"] = "Advanced"
        if m.get("data_type"):
            kw["DataType"] = m["data_type"]
        version = _put(ssm, **kw).get("Version")

    # Solo etiquetas: sin put, así no se crea versión nueva
    if fila.get("tags_poner"):
        ssm.add_tags_to_resource(ResourceType="Parameter", ResourceId=it["name"],
                                 Tags=[{"Key": k, "Value": v} for k, v in fila["tags_poner"].items()])
    if fila.get("tags_quitar"):
        ssm.remove_tags_from_resource(ResourceType="Parameter", ResourceId=it["name"],
                                      TagKeys=fila["tags_quitar"])
    return version
