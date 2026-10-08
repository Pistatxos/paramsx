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
