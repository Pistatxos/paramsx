"""El servidor web local de paramsx.

Seguridad: escucha solo en 127.0.0.1; la URL de arranque lleva un token aleatorio que se
guarda en una cookie de sesión (sin ella, 403); lo que cambia algo exige además que el
Origin sea el propio servidor; y todas las respuestas van con Cache-Control: no-store.
Los valores de los parámetros no se escriben nunca a disco: ni ficheros, ni logs, ni caché.
"""
import hmac
import logging
import os
import re
import secrets
import threading
import webbrowser

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from flask import Flask, jsonify, redirect, render_template, request

from .. import __version__
from ..core import config as core_config
from ..core.rutas import aplicar_case_ruta, build_full_path, grupo_desde_carpeta
from . import ssm as ssm_web

PUERTO_DEFECTO = 8765
HOSTS_LOCALES = ("127.0.0.1", "localhost")
REGIONES = [
    "eu-south-2", "eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1", "eu-central-2",
    "eu-south-1", "eu-north-1", "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "ca-central-1", "sa-east-1", "ap-south-1", "ap-northeast-1", "ap-northeast-2",
    "ap-southeast-1", "ap-southeast-2", "me-central-1", "af-south-1",
]
MAX_ITEMS = 2000


class ErrorWeb(Exception):
    def __init__(self, mensaje, status=400, **extra):
        super().__init__(mensaje)
        self.mensaje, self.status, self.extra = mensaje, status, extra


def _sesion_boto3(perfil, region):
    return boto3.Session(profile_name=perfil or None, region_name=region or None)


def crear_app(config_path=None, token=None, sesion_factory=None, perfiles_aws=None):
    """`sesion_factory(perfil, region)` devuelve algo con .client(); se inyecta en los tests."""
    app = Flask(__name__)
    # El orden de 'perfiles' importa (sin perfil_nuevos se usa el primero): no se reordena
    app.json.sort_keys = False
    config_path = config_path or core_config.CONFIG_PATH
    token = token or secrets.token_urlsafe(32)
    sesion_factory = sesion_factory or _sesion_boto3
    app.config["PX_TOKEN"] = token

    sesiones, cuentas, cerrojo = {}, {}, threading.Lock()

    def sesion(perfil, region):
        with cerrojo:
            clave = (perfil, region)
            if clave not in sesiones:
                sesiones[clave] = sesion_factory(perfil, region)
            return sesiones[clave]

    # ------------------------------------------------------------ config

    def leer_config():
        """(config, existe, error). Si no hay fichero, la plantilla; nunca se ejecuta."""
        if not os.path.exists(config_path):
            return core_config.config_plantilla(), False, ""
        try:
            return core_config.cargar_config_literal(config_path), True, ""
        except (ValueError, OSError) as e:
            return None, True, str(e)

    def config_activa():
        config, _, error = leer_config()
        if config is None:
            raise ErrorWeb(f"No se puede leer {config_path}: {error}")
        return config

    def donde():
        config = config_activa()
        return config.get("profile_name") or "default", config.get("region_name") or ""

    def ssm():
        perfil, region = donde()
        return ssm_web.cliente(sesion(perfil, region), region)

    def cuenta(perfil, region, forzar=False):
        clave = (perfil, region)
        if forzar or clave not in cuentas:
            sts = sesion(perfil, region).client("sts", region_name=region or None)
            ident = sts.get_caller_identity()
            cuentas[clave] = {"account": ident["Account"], "arn": ident["Arn"]}
        return cuentas[clave]

    def rutas_de(entrada, config):
        perfil = config["perfiles"].get(core_config.perfil_de(entrada))
        rutas = {}
        for entorno in config["entornos"]:
            try:
                rutas[str(entorno).lower()] = build_full_path(entrada["path"], perfil, str(entorno).lower())
            except (ValueError, AttributeError, TypeError, KeyError):
                rutas[str(entorno).lower()] = None
        return rutas

    casa = os.path.expanduser("~")
    corto = "~" + config_path[len(casa):] if config_path.startswith(casa + os.sep) else config_path

    def estado():
        config, existe, error = leer_config()
        if config is None:
            return {"version": __version__, "config_path": config_path, "config_path_corto": corto, "existe": existe,
                    "error_lectura": error, "config": None, "errores": [], "avisos": []}
        errores, avisos = core_config.validate_config(config)
        grupos = []
        if isinstance(config.get("parameter_list"), list):
            for entrada in config["parameter_list"]:
                if isinstance(entrada, dict) and isinstance(entrada.get("path"), str):
                    grupos.append({"nombre": entrada.get("nombre") or entrada["path"],
                                   "path": entrada["path"], "perfil": core_config.perfil_de(entrada),
                                   "rutas": rutas_de(entrada, config) if isinstance(config.get("perfiles"), dict) else {}})
        return {"version": __version__, "config_path": config_path, "config_path_corto": corto, "existe": existe,
                "error_lectura": "", "config": config, "grupos": grupos,
                "errores": errores, "avisos": avisos}

    def config_de_formulario(datos):
        """La config que manda Ajustes, con los tipos comprobados (la validación de verdad es
        validate_config, la misma de la terminal)."""
        if not isinstance(datos, dict):
            raise ErrorWeb("Config no válida.")

        def lista_str(v):
            return [str(x).strip() for x in (v or []) if str(x).strip()] if isinstance(v, list) else []

        perfiles = datos.get("perfiles")
        if not isinstance(perfiles, dict):
            raise ErrorWeb("'perfiles' debe ser un diccionario.")
        entradas = []
        for e in datos.get("parameter_list") or []:
            if not isinstance(e, dict):
                continue
            entrada = {"path": str(e.get("path") or "").strip(), "perfil": str(e.get("perfil") or "")}
            nombre = str(e.get("nombre") or "").strip()
            if nombre and nombre != entrada["path"]:
                entrada = {"nombre": nombre[:60], **entrada}
            entradas.append(entrada)
        return {
            "profile_name": str(datos.get("profile_name") or "").strip() or "default",
            "region_name": str(datos.get("region_name") or "").strip(),
            "entornos": lista_str(datos.get("entornos")),
            "parameter_list": entradas,
            "perfiles": {str(k).strip(): {"posicion_entorno": str(p.get("posicion_entorno")),
                                          "case_entorno": str(p.get("case_entorno") or "lower"),
                                          "case_ruta": str(p.get("case_ruta") or "ninguno")}
                         for k, p in perfiles.items() if str(k).strip() and isinstance(p, dict)},
            "perfil_nuevos": str(datos.get("perfil_nuevos") or ""),
            "fichero_por_ruta": bool(datos.get("fichero_por_ruta", False)),
            "forzar_securestring": bool(datos.get("forzar_securestring", True)),
            "tags_activas": bool(datos.get("tags_activas", True)),
            "obligatorias_vacias": bool(datos.get("obligatorias_vacias", False)),
            "tags_obligatorias": lista_str(datos.get("tags_obligatorias")),
        }

    def validar_formulario(config):
        errores, avisos = core_config.validate_config(config)
        if not config["region_name"]:
            errores.insert(0, "Elige la región de AWS.")
        if len(set(e.lower() for e in config["entornos"])) != len(config["entornos"]):
            errores.append("Hay entornos repetidos.")
        return errores, avisos

    def guardar(config):
        errores, avisos = validar_formulario(config)
        if errores:
            raise ErrorWeb("La configuración tiene errores.", errores=errores, avisos=avisos)
        _, _, error = leer_config()
        if error:
            raise ErrorWeb(f"No se sobrescribe {config_path}: {error}")
        core_config.guardar_config(config, config_path)

    # ------------------------------------------------------------ seguridad

    def nombre_cookie():
        return "paramsx_" + re.sub(r"\W", "_", request.host)

    @app.before_request
    def proteger():
        if request.host.rsplit(":", 1)[0] not in HOSTS_LOCALES:
            return "Host no permitido.", 403
        dado = request.args.get("token")
        if request.path == "/" and dado:
            if not hmac.compare_digest(dado, token):
                return "Token no válido: abre la URL que sale en la terminal.", 403
            resp = redirect("/")
            resp.set_cookie(nombre_cookie(), token, httponly=True, samesite="Strict", path="/")
            return resp
        if not hmac.compare_digest(request.cookies.get(nombre_cookie(), ""), token):
            return "Abre la URL que sale en la terminal al arrancar paramsx (lleva el token).", 403
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("Origin") != f"http://{request.host}":
                return jsonify({"error": "Origen no permitido."}), 403

    @app.after_request
    def cabeceras(resp):
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        return resp

    @app.errorhandler(ErrorWeb)
    def error_web(e):
        return jsonify({"error": e.mensaje, **e.extra}), e.status

    @app.errorhandler(ssm_web.ParametrosError)
    def error_parametros(e):
        return jsonify({"error": str(e)}), 400

    @app.errorhandler(ClientError)
    def error_cliente(e):
        if ssm_web.codigo(e) in ("ExpiredToken", "ExpiredTokenException", "UnrecognizedClientException",
                                 "InvalidClientTokenId"):
            return jsonify({"error": f"Credenciales de AWS caducadas o no válidas ({ssm_web.codigo(e)}). "
                                     "Si usas SSO: aws sso login --profile <perfil>."}), 400
        return jsonify({"error": ssm_web.motivo(e)}), 400

    @app.errorhandler(BotoCoreError)
    def error_botocore(e):
        return jsonify({"error": f"AWS: {e}"}), 400

    def cuerpo():
        datos = request.get_json(silent=True)
        if not isinstance(datos, dict):
            raise ErrorWeb("Petición no válida.")
        return datos

    def items_de(datos):
        items = datos.get("items")
        if not isinstance(items, list) or not items or len(items) > MAX_ITEMS:
            raise ErrorWeb("No hay cambios que revisar.")
        return [it for it in items if isinstance(it, dict)]

    # ------------------------------------------------------------ páginas

    @app.get("/")
    def inicio():
        return render_template("index.html", version=__version__)

    @app.get("/api/estado")
    def api_estado():
        return jsonify(estado())

    @app.get("/api/aws/perfiles")
    def api_perfiles():
        try:
            disponibles = perfiles_aws if perfiles_aws is not None else boto3.Session().available_profiles
        except BotoCoreError:
            disponibles = []
        return jsonify({"perfiles": sorted(disponibles), "regiones": REGIONES})

    @app.post("/api/aws/probar")
    def api_probar():
        datos = cuerpo()
        perfil = str(datos.get("profile_name") or "default")
        region = str(datos.get("region_name") or "")
        with cerrojo:
            sesiones.pop((perfil, region), None)
        return jsonify(cuenta(perfil, region, forzar=True))

    @app.get("/api/cuenta")
    def api_cuenta():
        perfil, region = donde()
        return jsonify({"profile_name": perfil, "region_name": region, **cuenta(perfil, region)})

    @app.post("/api/config/revisar")
    def api_config_revisar():
        config = config_de_formulario(cuerpo().get("config"))
        errores, avisos = validar_formulario(config)
        muestra = (config["entornos"] or ["dev"])[0].lower()
        resultados = []
        for entrada in config["parameter_list"]:
            perfil = config["perfiles"].get(entrada["perfil"])
            try:
                resultados.append(f"{muestra} → {build_full_path(entrada['path'], perfil, muestra)}"
                                  if perfil else "perfil que no existe")
            except ValueError as e:
                resultados.append(str(e))
        return jsonify({"errores": errores, "avisos": avisos, "resultados": resultados})

    @app.put("/api/config")
    def api_config_guardar():
        guardar(config_de_formulario(cuerpo().get("config")))
        return jsonify(estado())

    @app.post("/api/grupo-de")
    def api_grupo_de():
        datos = cuerpo()
        try:
            entrada, perfil_nuevo = grupo_desde_carpeta(
                datos.get("carpeta", ""), datos.get("entornos") or [], datos.get("perfiles") or {})
        except ValueError as e:
            raise ErrorWeb(str(e))
        return jsonify({"grupo": entrada, "perfil_nuevo": perfil_nuevo})

    @app.post("/api/grupos")
    def api_grupos_anadir():
        """«+ Grupo» de Explorar: se añade a la config del disco y se guarda."""
        config = config_activa()
        try:
            entrada, perfil_nuevo = grupo_desde_carpeta(
                cuerpo().get("carpeta", ""), config["entornos"], config["perfiles"])
        except ValueError as e:
            raise ErrorWeb(str(e))
        lista = config.get("parameter_list") or []
        if any(isinstance(e, dict) and e.get("path") == entrada["path"]
               and core_config.perfil_de(e) == entrada["perfil"] for e in lista):
            raise ErrorWeb(f"El grupo {entrada['path']} ({entrada['perfil']}) ya está.")
        if perfil_nuevo:
            config["perfiles"][perfil_nuevo[0]] = perfil_nuevo[1]
        config["parameter_list"] = [*lista, entrada]
        guardar(config_de_formulario(config))
        return jsonify({"grupo": entrada, "perfil_nuevo": perfil_nuevo, "estado": estado()})

    @app.post("/api/nombre-nuevo")
    def api_nombre_nuevo():
        """El nombre de un parámetro nuevo con el case_ruta del perfil (como la opción 4)."""
        datos = cuerpo()
        base, nombre = str(datos.get("base") or "").rstrip("/"), str(datos.get("nombre") or "")
        config = config_activa()
        perfil = config["perfiles"].get(datos.get("perfil") or config.get("perfil_nuevos")) or {}
        case = perfil.get("case_ruta", "ninguno")
        if base and nombre.startswith(base + "/") and len(nombre) > len(base) + 1:
            nombre = base + aplicar_case_ruta(nombre[len(base):], case)
        elif not base and nombre.startswith("/"):
            nombre = aplicar_case_ruta(nombre, case)
        return jsonify({"nombre": nombre})

    @app.get("/api/explorar")
    def api_explorar():
        return jsonify(ssm_web.explorar(ssm(), request.args.get("prefijo") or "/"))

    @app.post("/api/cargar")
    def api_cargar():
        ruta = str(cuerpo().get("ruta") or "").strip()
        if not ruta.startswith("/"):
            raise ErrorWeb("La ruta empieza por /.")
        return jsonify(ssm_web.cargar(ssm(), ruta))

    @app.post("/api/plan")
    def api_plan():
        items = items_de(cuerpo())
        perfil, region = donde()
        return jsonify({"plan": ssm_web.plan(ssm(), items, config_activa()),
                        **cuenta(perfil, region), "region_name": region})

    @app.post("/api/aplicar")
    def api_aplicar():
        datos = cuerpo()
        items = items_de(datos)
        perfil, region = donde()
        account = cuenta(perfil, region)["account"]
        if str(datos.get("confirmacion") or "").strip() != f"APLICAR EN {account}":
            raise ErrorWeb(f"Para aplicar escribe exactamente: APLICAR EN {account}")
        borrados = sum(1 for it in items if it.get("accion") == "borrar")
        if borrados and str(datos.get("borrados") or "").strip() != str(borrados):
            raise ErrorWeb(f"Se van a borrar {borrados}: escribe {borrados} para confirmarlo.")
        return jsonify({"resultados": ssm_web.aplicar(ssm(), items, config_activa())})

    @app.post("/api/historial")
    def api_historial():
        nombre = str(cuerpo().get("nombre") or "")
        if not nombre:
            raise ErrorWeb("Falta el nombre.")
        return jsonify({"versiones": ssm_web.historial(ssm(), nombre)})

    return app


def arrancar(puerto=PUERTO_DEFECTO, abrir_navegador=True, config_path=None):
    """Arranca el servidor en 127.0.0.1 en el primer puerto libre desde `puerto` y abre el
    navegador. Ctrl+C para cerrar."""
    from werkzeug.serving import make_server

    # Las líneas de petición de werkzeug no llevan valores (todo va en el cuerpo), pero
    # tampoco aportan nada en la terminal
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    app = crear_app(config_path=config_path)
    servidor = None
    for p in range(puerto, puerto + 50):
        try:
            servidor = make_server("127.0.0.1", p, app, threaded=True)
            break
        except OSError:
            continue
    if servidor is None:
        print(f"No hay ningún puerto libre entre {puerto} y {puerto + 49}.")
        return

    url = f"http://127.0.0.1:{servidor.server_port}/?token={app.config['PX_TOKEN']}"
    print(f"ParamsX web {__version__} en {url}", flush=True)
    print("Solo escucha en este equipo. Ctrl+C para cerrar.", flush=True)
    if abrir_navegador:
        threading.Timer(0.4, webbrowser.open, [url]).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nParamsX web cerrado.")
    finally:
        servidor.server_close()
