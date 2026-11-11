"""La versión web contra un SSM simulado: seguridad, carga con permisos parciales, plan,
aplicar, historial y que ningún valor acabe en disco."""
import logging
import os

import pytest

from paramsx.web import ssm as ssm_web

from conftest import CUENTA, TOKEN, FakeSesion

TAGS = {"Application": "app", "Environment": "dev"}
CONFIRMA = f"APLICAR EN {CUENTA}"


def cargar(cliente, ruta="/dev/app"):
    r = cliente.post("/api/cargar", json={"ruta": ruta})
    assert r.status_code == 200, r.get_json()
    return {p["name"]: p for p in r.get_json()["parametros"]}


def item(p, accion="editar", **cambios):
    base = {"name": p["name"], "accion": accion, "version": p.get("version"), "value": p.get("value"),
            "description": p.get("description", ""), "type": p.get("type"), "tags": p.get("tags")}
    base.update(cambios)
    return base


# ---------------------------------------------------------------- seguridad

def test_sin_token_403(ssm, config_path):
    from paramsx.web.app import crear_app
    app = crear_app(config_path=config_path, token=TOKEN, sesion_factory=lambda p, r: FakeSesion(ssm))
    c = app.test_client()
    assert c.get("/", base_url="http://127.0.0.1:8765").status_code == 403
    assert c.get("/api/estado", base_url="http://127.0.0.1:8765").status_code == 403
    assert c.get("/?token=otro", base_url="http://127.0.0.1:8765").status_code == 403
    # Host que no es local (DNS rebinding)
    assert c.get(f"/?token={TOKEN}", base_url="http://evil.example:8765").status_code == 403


def test_token_cookie_origin_y_no_store(cliente):
    r = cliente.get("/api/estado")
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"
    # Con cookie pero sin Origin (o con otro), lo que cambia algo se rechaza
    sin_origin = cliente.crudo.post("/api/cargar", json={"ruta": "/dev"}, base_url="http://127.0.0.1:8765")
    assert sin_origin.status_code == 403
    otro = cliente.crudo.post("/api/cargar", json={"ruta": "/dev"}, base_url="http://127.0.0.1:8765",
                              headers={"Origin": "http://evil.example"})
    assert otro.status_code == 403


def test_cookie_httponly_samesite(ssm, config_path):
    from paramsx.web.app import crear_app
    app = crear_app(config_path=config_path, token=TOKEN, sesion_factory=lambda p, r: FakeSesion(ssm))
    r = app.test_client().get(f"/?token={TOKEN}", base_url="http://127.0.0.1:8765")
    cookie = r.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and r.headers["Location"] == "/"


# ---------------------------------------------------------------- estado, perfiles y config

def test_estado_con_grupos_resueltos(cliente):
    st = cliente.get("/api/estado").get_json()
    assert st["errores"] == []
    assert st["grupos"][1]["rutas"] == {"dev": "/API/STA/DEV", "pre": "/API/STA/PRE", "prod": "/API/STA/PROD"}
    assert cliente.get("/api/aws/perfiles").get_json()["perfiles"] == ["default", "stan"]
    assert cliente.post("/api/aws/probar", json={"profile_name": "stan", "region_name": "eu-south-2"}).get_json()["account"] == CUENTA


def test_guardar_config_valida_junto(cliente, config_path):
    cfg = cliente.get("/api/estado").get_json()["config"]
    cfg["parameter_list"] = [{"path": "/API/STA", "perfil": "min"}, {"path": "/x/*/y", "perfil": "min"},
                             {"path": "/a", "perfil": "nada"}]
    r = cliente.put("/api/config", json={"config": cfg})
    assert r.status_code == 400
    errores = r.get_json()["errores"]
    assert len(errores) == 2 and any("'*'" in e for e in errores) and any("nada" in e for e in errores)
    assert "/x/*/y" not in open(config_path).read()  # no se ha tocado

    cfg["parameter_list"] = [{"nombre": "STA", "path": "/API/STA", "perfil": "max"}]
    assert cliente.put("/api/config", json={"config": cfg}).status_code == 200
    assert '"nombre": "STA"' in open(config_path).read()


def test_revisar_config_al_vuelo(cliente):
    cfg = cliente.get("/api/estado").get_json()["config"]
    r = cliente.post("/api/config/revisar", json={"config": cfg}).get_json()
    assert r["resultados"] == ["dev → /dev/app", "dev → /API/STA/DEV"]


def test_anadir_grupo_desde_explorar(cliente, config_path):
    r = cliente.post("/api/grupos", json={"carpeta": "/API/MULTI/DEV/ia"})
    assert r.status_code == 200
    g = r.get_json()
    assert g["grupo"]["path"] == "/API/MULTI/*/ia" and g["perfil_nuevo"][0] == "mixto_upper"
    assert g["estado"]["grupos"][-1]["rutas"]["pre"] == "/API/MULTI/PRE/ia"
    # Sin duplicar
    assert cliente.post("/api/grupos", json={"carpeta": "/API/MULTI/DEV/ia"}).status_code == 400


def test_nombre_nuevo_con_case_ruta(cliente):
    r = cliente.post("/api/nombre-nuevo", json={"base": "/dev/app", "nombre": "/dev/app/Mi/CLAVE", "perfil": "min"})
    assert r.get_json()["nombre"] == "/dev/app/mi/clave"


# ---------------------------------------------------------------- carga y permisos

def test_carga_normal(cliente, ssm):
    ssm.poner("/dev/app/db", '{"user": "u"}', descripcion="La base", tags=TAGS, key_id="alias/mia")
    ssm.poner("/dev/app/url", "https://x", tipo="String")
    ps = cargar(cliente)
    assert ps["/dev/app/db"]["value"] == '{"user": "u"}' and ps["/dev/app/db"]["kms_propia"]
    assert ps["/dev/app/db"]["description"] == "La base" and ps["/dev/app/db"]["tags"] == TAGS
    assert ps["/dev/app/url"]["type"] == "String" and not ps["/dev/app/url"]["kms_propia"]
    assert all(kw["MaxResults"] == 10 for kw in ssm.ops("GetParametersByPath"))


def test_carga_kms_y_iam_bloqueados(cliente, ssm):
    for n in ("a", "b", "c"):
        ssm.poner(f"/dev/app/{n}", f"valor-{n}", tags=TAGS)
    ssm.kms_bloqueados.add("/dev/app/b")
    ssm.iam_bloqueados.add("/dev/app/c")
    ps = cargar(cliente)
    assert ps["/dev/app/a"]["value"] == "valor-a" and not ps["/dev/app/a"]["bloqueado"]
    assert ps["/dev/app/b"]["bloqueado"] == "Sin permiso para descifrarlo (KMS)."
    assert ps["/dev/app/c"]["bloqueado"] == "Tu rol de IAM no tiene permiso."
    assert ps["/dev/app/b"]["value"] is None


def test_carga_ruta_denegada_va_de_10_en_10(cliente, ssm):
    for i in range(23):
        ssm.poner(f"/dev/app/p{i:02}", f"v{i}")
    ssm.rutas_denegadas.add("/dev/app/")
    ps = cargar(cliente)
    assert len(ps) == 23 and all(p["value"] for p in ps.values())
    assert [len(kw["Names"]) for kw in ssm.ops("GetParameters")] == [10, 10, 3]


def test_carga_sin_describe_ni_lectura(cliente, ssm):
    ssm.poner("/dev/app/a", "x")
    ssm.sin_describe = True
    ssm.rutas_denegadas.add("/dev/app/")
    r = cliente.post("/api/cargar", json={"ruta": "/dev/app"})
    assert r.status_code == 400 and "no puede listar ni leer" in r.get_json()["error"]


# ---------------------------------------------------------------- plan

def test_plan_conflicto_de_version(cliente, ssm):
    ssm.poner("/dev/app/a", "uno", tags=TAGS)
    p = cargar(cliente)["/dev/app/a"]
    ssm.poner("/dev/app/a", "otro")  # alguien lo cambia mientras tanto
    fila = cliente.post("/api/plan", json={"items": [item(p, value="dos")]}).get_json()["plan"][0]
    assert fila["conflicto"] and "recarga el grupo" in fila["errores"][0].lower()
    # Y aplicar no lo toca
    r = cliente.post("/api/aplicar", json={"items": [item(p, value="dos")], "confirmacion": CONFIRMA}).get_json()
    assert not r["resultados"][0]["ok"] and ssm.params["/dev/app/a"]["value"] == "otro"


def test_plan_avisos_y_validaciones(cliente, ssm):
    ssm.poner("/dev/app/a", "uno", tags=TAGS)
    p = cargar(cliente)["/dev/app/a"]
    plan = cliente.post("/api/plan", json={"items": [
        item(p, type="String", value="x" * 5000),
        {"name": "/dev/app/nuevo", "accion": "nuevo", "value": "", "type": "String", "description": "d" * 1100,
         "tags": {"Application": "", "aws:x": "1"}},
        {"name": "/aws/x", "accion": "nuevo", "value": "v", "type": "String", "tags": TAGS},
    ]}).get_json()["plan"]
    assert {"valor", "tipo"} <= set(plan[0]["cambios"])
    assert any("Deja de ser SecureString" in a for a in plan[0]["avisos"])
    assert any("Advanced" in a for a in plan[0]["avisos"])
    errores = " ".join(plan[1]["errores"])
    for texto in ("vacío", "1024", "aws:", "Environment"):
        assert texto in errores
    assert any("aws" in e for e in plan[2]["errores"])


# ---------------------------------------------------------------- aplicar

def test_aplicar_conserva_kms_descripcion_tier_y_tipo(cliente, ssm):
    ssm.poner("/dev/app/a", "uno", descripcion="Desc", tags=TAGS, key_id="alias/mia", tier="Advanced")
    ssm.poner("/dev/app/b", "dos", tipo="String", descripcion="Otra", tags=TAGS)
    ps = cargar(cliente)
    r = cliente.post("/api/aplicar", json={"items": [
        item(ps["/dev/app/a"], value="uno-bis"),
        item(ps["/dev/app/b"], value="x" * 5000),
    ], "confirmacion": CONFIRMA}).get_json()
    assert all(x["ok"] for x in r["resultados"]), r
    put_a, put_b = ssm.ops("PutParameter")
    assert put_a["KeyId"] == "alias/mia" and put_a["Tier"] == "Advanced" and put_a["Description"] == "Desc"
    assert "Type" not in put_a and put_a["Overwrite"] is True
    assert put_b["Tier"] == "Advanced" and put_b["Description"] == "Otra" and "KeyId" not in put_b
    assert ssm.params["/dev/app/a"]["key_id"] == "alias/mia"
    assert ssm.params["/dev/app/a"]["description"] == "Desc"


def test_aplicar_cambio_de_tipo_manda_type(cliente, ssm):
    ssm.poner("/dev/app/a", "uno", tipo="String", tags=TAGS)
    p = cargar(cliente)["/dev/app/a"]
    cliente.post("/api/aplicar", json={"items": [item(p, type="SecureString")], "confirmacion": CONFIRMA})
    assert ssm.ops("PutParameter")[0]["Type"] == "SecureString"


def test_aplicar_solo_etiquetas_sin_put(cliente, ssm):
    ssm.poner("/dev/app/a", "uno", tags={**TAGS, "Vieja": "1"})
    p = cargar(cliente)["/dev/app/a"]
    tags = {**TAGS, "Owner": "mario", "Vieja": ""}
    r = cliente.post("/api/aplicar", json={"items": [item(p, tags=tags)], "confirmacion": CONFIRMA}).get_json()
    assert r["resultados"][0]["ok"] and r["resultados"][0]["version"] is None
    assert ssm.ops("PutParameter") == []
    assert ssm.ops("AddTagsToResource")[0]["Tags"] == [{"Key": "Owner", "Value": "mario"}]
    assert ssm.ops("RemoveTagsFromResource")[0]["TagKeys"] == ["Vieja"]
    assert ssm.params["/dev/app/a"]["version"] == 1


def test_aplicar_nuevo_con_etiquetas(cliente, ssm):
    nuevo = {"name": "/dev/app/n", "accion": "nuevo", "value": "v", "type": "SecureString", "description": "",
             "tags": {**TAGS, "Owner": ""}}
    r = cliente.post("/api/aplicar", json={"items": [nuevo], "confirmacion": CONFIRMA}).get_json()
    assert r["resultados"][0]["ok"]
    put = ssm.ops("PutParameter")[0]
    assert put["Overwrite"] is False and put["Tags"] == [{"Key": k, "Value": v} for k, v in TAGS.items()]
    assert "Description" not in put


def test_aplicar_borra_de_10_en_10_y_pide_confirmacion(cliente, ssm):
    for i in range(25):
        ssm.poner(f"/dev/app/p{i:02}", "v")
    ps = cargar(cliente)
    items = [item(p, accion="borrar") for p in ps.values()]
    r = cliente.post("/api/aplicar", json={"items": items, "confirmacion": CONFIRMA, "borrados": "24"})
    assert r.status_code == 400 and ssm.ops("DeleteParameters") == []
    r = cliente.post("/api/aplicar", json={"items": items, "confirmacion": "APLICAR EN 999", "borrados": "25"})
    assert r.status_code == 400
    r = cliente.post("/api/aplicar", json={"items": items, "confirmacion": CONFIRMA, "borrados": "25"}).get_json()
    assert all(x["ok"] for x in r["resultados"]) and not ssm.params
    assert [len(kw["Names"]) for kw in ssm.ops("DeleteParameters")] == [10, 10, 5]


def test_aplicar_reintenta_too_many_updates_y_sigue(cliente, ssm, monkeypatch):
    monkeypatch.setattr(ssm_web.time, "sleep", lambda s: None)
    ssm.poner("/dev/app/a", "uno", tags=TAGS)
    ssm.poner("/dev/app/b", "dos", tags=TAGS)
    ps = cargar(cliente)
    ssm.too_many = {"/dev/app/a": 2, "/dev/app/b": 5}
    r = cliente.post("/api/aplicar", json={"items": [item(ps["/dev/app/a"], value="1"), item(ps["/dev/app/b"], value="2")],
                                           "confirmacion": CONFIRMA}).get_json()["resultados"]
    assert r[0]["ok"] and not r[1]["ok"] and "Demasiados cambios" in r[1]["error"]


# ---------------------------------------------------------------- historial

def test_historial(cliente, ssm):
    for i in range(1, 121):
        ssm.poner("/dev/app/a", f"v{i}")
    v = cliente.post("/api/historial", json={"nombre": "/dev/app/a"}).get_json()["versiones"]
    assert len(v) == 100 and v[0]["version"] == 120 and v[0]["value"] == "v120"
    assert all(kw["MaxResults"] <= 50 for kw in ssm.ops("GetParameterHistory"))


# ---------------------------------------------------------------- ningún valor a disco

def test_ningun_valor_acaba_en_disco(cliente, ssm, config_path, tmp_path, monkeypatch, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    monkeypatch.chdir(tmp_path)
    secretos = ["S3CRETO-uno-7f3a", "S3CRETO-nuevo-91bc", "S3CRETO-hist-0d2e"]
    ssm.poner("/dev/app/a", secretos[2], tags=TAGS)
    ssm.poner("/dev/app/a", secretos[0], tags=TAGS)
    p = cargar(cliente)["/dev/app/a"]
    nuevo = {"name": "/dev/app/n", "accion": "nuevo", "value": secretos[1], "type": "SecureString", "tags": TAGS}
    cliente.post("/api/plan", json={"items": [item(p, value=secretos[0] + "x"), nuevo]})
    cliente.post("/api/aplicar", json={"items": [item(p, value=secretos[0] + "x"), nuevo], "confirmacion": CONFIRMA})
    cliente.post("/api/historial", json={"nombre": "/dev/app/a"})
    cliente.get("/api/explorar")
    cliente.put("/api/config", json={"config": cliente.get("/api/estado").get_json()["config"]})

    salida = capsys.readouterr()
    textos = [caplog.text, salida.out, salida.err]
    for raiz in {str(tmp_path), os.path.dirname(config_path)}:
        for carpeta, _, ficheros in os.walk(raiz):
            for f in ficheros:
                with open(os.path.join(carpeta, f), "rb") as fh:
                    textos.append(fh.read().decode("utf-8", "replace"))
    for s in secretos:
        assert not any(s in t for t in textos), f"{s} ha acabado en disco o en un log"


def test_guardar_no_reordena_perfiles(cliente, config_path):
    from paramsx.core import config as core_config
    cfg = cliente.get("/api/estado").get_json()["config"]
    assert list(cfg["perfiles"]) == ["min", "max"]
    assert cliente.put("/api/config", json={"config": cfg}).status_code == 200
    assert list(core_config.cargar_config_literal(config_path)["perfiles"]) == ["min", "max"]


def renombrar(p, nuevo):
    """Lo que manda «Reemplazar» en nombres: el alta del nuevo (con «de») y el borrado del viejo."""
    return [item(p, accion="nuevo", name=nuevo, version=None, de=p["name"]), item(p, accion="borrar")]


def test_renombrar_conserva_la_clave_kms_y_nunca_pierde_el_viejo(cliente, ssm, monkeypatch):
    clave = "arn:aws:kms:eu-south-2:1:key/propia"
    ssm.poner("/dev/app/db", "secreto", tags=TAGS, key_id=clave)
    ssm.poner("/dev/app/url", "https://x", tipo="String", tags=TAGS)
    ssm.poner("/dev/app/grande", "ya estaba", tipo="String", tags=TAGS)
    ps = cargar(cliente)
    r = cliente.post("/api/aplicar", json={"items": renombrar(ps["/dev/app/db"], "/dev/app/db2"),
                                           "confirmacion": CONFIRMA, "borrados": "1"}).get_json()
    assert all(x["ok"] for x in r["resultados"]), r
    assert ssm.ops("PutParameter")[0]["KeyId"] == clave  # la clave propia del viejo, no la de por defecto
    assert ssm.params["/dev/app/db2"]["key_id"] == clave and "/dev/app/db" not in ssm.params

    # El nuevo nombre ya existe en AWS: la revisión no deja borrar el viejo
    filas = {f["name"]: f for f in cliente.post("/api/plan", json={
        "items": renombrar(ps["/dev/app/url"], "/dev/app/grande")}).get_json()["plan"]}
    assert "No se borra" in " ".join(filas["/dev/app/url"]["errores"])

    # Y si falla al crearlo en AWS (aquí, otro lo crea justo antes), el viejo tampoco se borra
    real = ssm.put_parameter

    def lo_crea_otro(**kw):
        if kw["Name"] not in ssm.params:
            ssm.poner(kw["Name"], "de otro", tipo="String")
        return real(**kw)
    monkeypatch.setattr(ssm, "put_parameter", lo_crea_otro)
    r = {x["name"]: x for x in cliente.post("/api/aplicar", json={
        "items": renombrar(ps["/dev/app/url"], "/dev/app/url2"), "confirmacion": CONFIRMA,
        "borrados": "1"}).get_json()["resultados"]}
    assert not r["/dev/app/url2"]["ok"] and not r["/dev/app/url"]["ok"]
    assert "No se borra" in r["/dev/app/url"]["error"]
    assert "/dev/app/url" in ssm.params and not [o for o in ssm.ops("DeleteParameters") if "/dev/app/url" in o["Names"]]


def test_si_el_original_cambia_mientras_se_aplica_no_se_borra(cliente, ssm, monkeypatch):
    ssm.poner("/dev/app/url", "https://x", tipo="String", tags=TAGS)
    ssm.poner("/dev/app/b", "b", tipo="String", tags=TAGS)
    ps = cargar(cliente)
    aplicar = lambda items: {x["name"]: x for x in cliente.post("/api/aplicar", json={  # noqa: E731
        "items": items, "confirmacion": CONFIRMA, "borrados": "1"}).get_json()["resultados"]}

    # Mientras se crea la copia renombrada, otro cambia el original
    real = ssm.put_parameter

    def y_otro_cambia_el_original(**kw):
        r = real(**kw)
        if kw["Name"] == "/dev/app/url2":
            real(Name="/dev/app/url", Value="https://nuevo", Overwrite=True)
        return r
    monkeypatch.setattr(ssm, "put_parameter", y_otro_cambia_el_original)
    r = aplicar(renombrar(ps["/dev/app/url"], "/dev/app/url2"))
    assert r["/dev/app/url2"]["ok"] and not r["/dev/app/url"]["ok"]
    assert "Ha cambiado en AWS mientras se aplicaba (versión 1 → 2)" in r["/dev/app/url"]["error"]
    assert "«/dev/app/url2»" in r["/dev/app/url"]["error"]  # avisa de la copia con el valor de antes
    assert ssm.params["/dev/app/url"]["value"] == "https://nuevo"  # el cambio del otro no se pierde
    assert ssm.ops("DeleteParameters") == []
    monkeypatch.setattr(ssm, "put_parameter", real)

    # Un borrado normal: lo cambian entre la revisión y el borrado
    revisar_real = ssm_web._revisar

    def revisa_y_cambia(*a, **k):
        out = revisar_real(*a, **k)
        ssm.poner("/dev/app/b", "b-de-otro", tipo="String")
        return out
    monkeypatch.setattr(ssm_web, "_revisar", revisa_y_cambia)
    r = aplicar([item(ps["/dev/app/b"], accion="borrar")])
    assert not r["/dev/app/b"]["ok"] and "Recarga el grupo" in r["/dev/app/b"]["error"]
    assert "/dev/app/b" in ssm.params and ssm.ops("DeleteParameters") == []

    # Sin permiso para volver a leerla: se borra como antes (ya se comprobó al revisar)
    def revisa_y_quita_describe(*a, **k):
        out = revisar_real(*a, **k)
        ssm.sin_describe = True
        return out
    monkeypatch.setattr(ssm_web, "_revisar", revisa_y_quita_describe)
    ssm.poner("/dev/app/c", "c", tipo="String")
    r = aplicar([{"name": "/dev/app/c", "accion": "borrar", "version": 1}])
    assert r["/dev/app/c"]["ok"] and "/dev/app/c" not in ssm.params
    ssm.sin_describe = False

    # Si falla de otra forma al leerla, no se borra (sin comprobar no se toca)
    def revisa_y_rompe(*a, **k):
        out = revisar_real(*a, **k)
        monkeypatch.setattr(ssm, "describe_parameters", lambda **kw: (_ for _ in ()).throw(
            ssm_web.ClientError({"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}}, "Op")))
        return out
    monkeypatch.setattr(ssm_web, "_revisar", revisa_y_rompe)
    ssm.poner("/dev/app/d", "d", tipo="String")
    r = aplicar([{"name": "/dev/app/d", "accion": "borrar", "version": 1}])
    assert not r["/dev/app/d"]["ok"] and "No se pudo comprobar" in r["/dev/app/d"]["error"]
    assert "/dev/app/d" in ssm.params
    monkeypatch.undo()

    # Sin cambios, se borra como siempre (b va ya por la versión 2)
    r = aplicar([{"name": "/dev/app/b", "accion": "borrar", "version": 2}])
    assert r["/dev/app/b"]["ok"] and "/dev/app/b" not in ssm.params


# ---------------------------------------------------------------- nombre sin barra final

def test_nuevo_con_barra_final_se_quita(cliente, ssm):
    nuevo = {"name": " /dev/app/n// ", "accion": "nuevo", "value": "v", "type": "String", "tags": TAGS}
    plan = cliente.post("/api/plan", json={"items": [dict(nuevo)]}).get_json()["plan"]
    assert plan[0]["name"] == "/dev/app/n" and not plan[0]["errores"]
    r = cliente.post("/api/aplicar", json={"items": [nuevo], "confirmacion": CONFIRMA}).get_json()
    assert r["resultados"][0]["ok"] and r["resultados"][0]["name"] == "/dev/app/n"
    assert ssm.ops("PutParameter")[0]["Name"] == "/dev/app/n" and "/dev/app/n" in ssm.params
    # Solo barras: no queda nombre, así que se deja y la revisión lo rechaza
    solo = cliente.post("/api/plan", json={"items": [{**nuevo, "name": "//"}]}).get_json()["plan"][0]
    assert solo["name"] == "//" and solo["errores"]


def test_editar_con_barra_final_no_se_toca(cliente, ssm):
    # Solo los nuevos: un existente se manda por su nombre tal cual
    plan = cliente.post("/api/plan", json={"items": [
        {"name": "/dev/app/x/", "accion": "editar", "value": "v", "type": "String", "tags": TAGS}]}).get_json()["plan"]
    assert plan[0]["name"] == "/dev/app/x/" and plan[0]["errores"]


# ---------------------------------------------------------------- JS: lo que no se aplicó no se pierde

def _funcion_js(fuente, nombre):
    """El código de `function nombre(...) {...}` de paramsx.js (va sangrado dos espacios dentro del IIFE)."""
    ini = fuente.index(f"  function {nombre}(")
    return fuente[ini:fuente.index("\n  }\n", ini) + 4]


def test_js_reponer_lo_no_aplicado(tmp_path):
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        pytest.skip("Sin node no se puede probar el JS")
    fuente = (Path(__file__).parent.parent / "paramsx/web/static/paramsx.js").read_text(encoding="utf-8")
    script = _funcion_js(fuente, "reponer") + r"""
    // Lo recién cargado de AWS: a se aplicó (v2), b no (falló), c era conflicto (en AWS ya va por v5)
    const de = (name, value, version) => ({ name, value, type: 'String', description: '', tags: { A: '1' }, borrar: false, nuevo: false,
      orig: { name, value, type: 'String', description: '', tags: { A: '1' }, version } });
    const items = [de('/r/a', 'a-nuevo', 2), de('/r/b', 'b', 1), de('/r/c', 'c-de-otro', 5), de('/r/d', 'd', 1)];
    const sinHacer = [
      { name: '/r/n1', value: 'v1', type: 'SecureString', description: 'uno', tags: { ManagedBy: 'paramsx' }, nuevo: true, borrar: false, orig: null },
      { name: '/r/n2', value: 'v2', type: 'String', description: '', tags: {}, nuevo: true, borrar: false, orig: null },
      { ...de('/r/b', 'b-editado', 1), description: 'desc', type: 'SecureString', tags: { A: '2' } },
      { ...de('/r/c', 'c-mio', 3) },
      { ...de('/r/d', 'd', 1), borrar: true },
      { ...de('/r/ya-no-esta', 'x', 1) },
    ];
    const r = reponer(items, sinHacer, new Set(['/r/c']));
    console.log(JSON.stringify(r));
    """
    ruta = tmp_path / "prueba.js"
    ruta.write_text(script, encoding="utf-8")
    out = json.loads(subprocess.run([node, str(ruta)], capture_output=True, text=True, check=True).stdout)
    por = {p["name"]: p for p in out}
    # Los nuevos, arriba y en su orden, con todo lo que llevaban
    assert [p["name"] for p in out[:2]] == ["/r/n1", "/r/n2"]
    assert por["/r/n1"]["value"] == "v1" and por["/r/n1"]["description"] == "uno" and por["/r/n1"]["type"] == "SecureString"
    assert por["/r/n1"]["tags"] == {"ManagedBy": "paramsx"}
    # Lo aplicado, como viene de AWS
    assert por["/r/a"]["value"] == "a-nuevo" and por["/r/a"]["orig"]["version"] == 2
    # Lo que falló, con lo editado otra vez encima de lo leído
    b = por["/r/b"]
    assert (b["value"], b["description"], b["type"], b["tags"]) == ("b-editado", "desc", "SecureString", {"A": "2"})
    assert b["orig"]["value"] == "b"
    # El conflicto conserva la versión que se cargó, para que la revisión lo siga marcando
    assert por["/r/c"]["value"] == "c-mio" and por["/r/c"]["orig"]["version"] == 3
    assert por["/r/d"]["borrar"] is True
    # Lo que ya no está en AWS no se inventa
    assert "/r/ya-no-esta" not in por and len(out) == 6


# ---------------------------------------------------------------- buscar un parámetro

def test_en_ruta_vale_el_nombre_de_un_parametro_o_uno_sin_carpeta(cliente, ssm):
    ssm.poner("/dev/app/clave", "x1")
    ssm.poner("SinCarpeta", "raiz", tipo="String")
    assert list(cargar(cliente, "/dev/app/clave")) == ["/dev/app/clave"]  # el nombre completo, no su carpeta
    assert cargar(cliente, "/dev/app/clave")["/dev/app/clave"]["value"] == "x1"
    assert cargar(cliente, "SinCarpeta")["SinCarpeta"]["value"] == "raiz"
    assert cargar(cliente, "/dev/no/existe") == {}
    assert cargar(cliente, "NoExiste") == {}


def test_explorar_busca_en_aws_lo_que_no_cabe_en_la_lista(cliente, ssm):
    ssm.poner("/dev/app/clave", "x1")
    ssm.poner("/prod/otra/Cosa", "x2")
    r = cliente.get("/api/explorar?contiene=Cosa").get_json()
    assert r["nombres"] == ["/prod/otra/Cosa"]
