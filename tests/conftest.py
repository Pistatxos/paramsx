"""SSM simulado para los tests. Cada llamada se valida contra el modelo real de botocore
(nombres de campos, obligatorios, longitudes), así que una petición mal formada falla aquí
igual que fallaría en AWS."""
import datetime
import os
import sys

import botocore.session
import pytest
from botocore.exceptions import ClientError
from botocore.validate import validate_parameters

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODELO = botocore.session.get_session().get_service_model("ssm")
CUENTA = "123456789012"


def error(codigo, mensaje="", op="Op"):
    return ClientError({"Error": {"Code": codigo, "Message": mensaje or codigo}}, op)


class FakeSSM:
    def __init__(self):
        self.params = {}
        self.llamadas = []
        self.rutas_denegadas = set()   # get_parameters_by_path da AccessDenied bajo estos prefijos
        self.kms_bloqueados = set()    # no se pueden descifrar
        self.iam_bloqueados = set()    # el rol no puede leerlos
        self.sin_describe = False
        self.too_many = {}             # nombre -> cuántos TooManyUpdates lanzar antes de aceptar
        self.reloj = datetime.datetime(2026, 10, 1, 9, 0, tzinfo=datetime.timezone.utc)

    # -------------------------------------------------------------- utilidades del test
    def poner(self, nombre, valor, tipo="SecureString", descripcion="", tags=None, key_id=None,
              tier="Standard", data_type="text"):
        if tipo == "SecureString" and key_id is None:
            key_id = "alias/aws/ssm"
        p = self.params.get(nombre)
        version = p["version"] + 1 if p else 1
        historia = p["history"] if p else []
        self.reloj += datetime.timedelta(minutes=1)
        nuevo = {"value": valor, "type": tipo, "description": descripcion, "key_id": key_id or "",
                 "tier": tier, "data_type": data_type, "version": version,
                 "tags": dict(tags or (p["tags"] if p else {})), "modified": self.reloj,
                 "user": "arn:aws:iam::123456789012:user/mario", "history": historia}
        historia.append({k: nuevo[k] for k in ("value", "type", "description", "version", "modified", "user")})
        del historia[:-100]  # AWS guarda las últimas 100
        self.params[nombre] = nuevo
        return nuevo

    def ops(self, nombre):
        return [kw for op, kw in self.llamadas if op == nombre]

    def _llamar(self, op, kw):
        validate_parameters(kw, MODELO.operation_model(op).input_shape)
        self.llamadas.append((op, kw))

    def _leible(self, n):
        if n in self.iam_bloqueados:
            raise error("AccessDeniedException", f"User is not authorized to perform ssm:GetParameter on {n}")
        if n in self.kms_bloqueados:
            raise error("AccessDeniedException", "The ciphertext refers to a key you are not allowed to "
                        "use (Service: AWSKMS; Status Code: 400; Error Code: AccessDeniedException)")

    def _salida(self, n):
        p = self.params[n]
        return {"Name": n, "Type": p["type"], "Value": p["value"], "Version": p["version"],
                "LastModifiedDate": p["modified"], "DataType": p["data_type"]}

    # -------------------------------------------------------------- API
    def describe_parameters(self, **kw):
        self._llamar("DescribeParameters", kw)
        if self.sin_describe:
            raise error("AccessDeniedException", "not authorized to perform ssm:DescribeParameters")
        nombres = sorted(self.params)
        for f in kw.get("ParameterFilters", []):
            if f["Key"] == "Path":
                base = f["Values"][0].rstrip("/") + "/"
                nombres = [n for n in nombres if n.startswith(base)]
            elif f["Key"] == "Name":
                nombres = [n for n in nombres if n in f["Values"]]
        inicio = int(kw.get("NextToken") or 0)
        pagina = nombres[inicio:inicio + kw.get("MaxResults", 50)]
        r = {"Parameters": [{
            "Name": n, "Type": self.params[n]["type"], "KeyId": self.params[n]["key_id"],
            "Tier": self.params[n]["tier"], "Version": self.params[n]["version"],
            "Description": self.params[n]["description"], "LastModifiedDate": self.params[n]["modified"],
            "LastModifiedUser": self.params[n]["user"], "DataType": self.params[n]["data_type"],
        } for n in pagina]}
        if inicio + len(pagina) < len(nombres):
            r["NextToken"] = str(inicio + len(pagina))
        return r

    def get_parameters_by_path(self, **kw):
        self._llamar("GetParametersByPath", kw)
        ruta = kw["Path"].rstrip("/") + "/"
        if any(ruta.startswith(d) for d in self.rutas_denegadas):
            raise error("AccessDeniedException", f"not authorized to perform ssm:GetParametersByPath on {ruta}")
        nombres = [n for n in sorted(self.params) if n.startswith(ruta)]
        inicio = int(kw.get("NextToken") or 0)
        pagina = nombres[inicio:inicio + kw.get("MaxResults", 10)]
        for n in pagina:  # si uno no se puede descifrar, la llamada entera falla (como en AWS)
            if n in self.kms_bloqueados:
                self._leible(n)
        visibles = [n for n in pagina if n not in self.iam_bloqueados]
        r = {"Parameters": [self._salida(n) for n in visibles]}
        if inicio + len(pagina) < len(nombres):
            r["NextToken"] = str(inicio + len(pagina))
        return r

    def get_parameters(self, **kw):
        self._llamar("GetParameters", kw)
        for n in kw["Names"]:
            if n in self.params:
                self._leible(n)
        return {"Parameters": [self._salida(n) for n in kw["Names"] if n in self.params],
                "InvalidParameters": [n for n in kw["Names"] if n not in self.params]}

    def get_parameter(self, **kw):
        self._llamar("GetParameter", kw)
        n = kw["Name"]
        if n not in self.params:
            raise error("ParameterNotFound")
        self._leible(n)
        return {"Parameter": self._salida(n)}

    def list_tags_for_resource(self, **kw):
        self._llamar("ListTagsForResource", kw)
        p = self.params.get(kw["ResourceId"])
        if p is None:
            raise error("InvalidResourceId")
        return {"TagList": [{"Key": k, "Value": v} for k, v in p["tags"].items()]}

    def put_parameter(self, **kw):
        self._llamar("PutParameter", kw)
        n = kw["Name"]
        if self.too_many.get(n):
            self.too_many[n] -= 1
            raise error("TooManyUpdates")
        existe = n in self.params
        if existe and not kw.get("Overwrite"):
            raise error("ParameterAlreadyExists")
        if not existe and "Type" not in kw:
            raise error("ValidationException", "Type is required when creating")
        anterior = self.params.get(n, {})
        tipo = kw.get("Type", anterior.get("type"))
        tier = kw.get("Tier", "Standard")
        if anterior.get("tier") == "Advanced" and tier == "Standard":
            raise error("ValidationException", "You can't downgrade an advanced parameter")
        if tier == "Standard" and len(kw["Value"].encode()) > 4096:
            raise error("ValidationException", "Standard tier max 4 KB")
        # Lo que hace Overwrite con lo que no se manda: la descripción se pierde y una clave
        # KMS propia vuelve a la de por defecto
        self.poner(n, kw["Value"], tipo, kw.get("Description", ""),
                   tags={t["Key"]: t["Value"] for t in kw.get("Tags", [])} if not existe else None,
                   key_id=kw.get("KeyId") if tipo == "SecureString" else "", tier=tier,
                   data_type=kw.get("DataType", "text"))
        return {"Version": self.params[n]["version"], "Tier": tier}

    def add_tags_to_resource(self, **kw):
        self._llamar("AddTagsToResource", kw)
        self.params[kw["ResourceId"]]["tags"].update({t["Key"]: t["Value"] for t in kw["Tags"]})
        return {}

    def remove_tags_from_resource(self, **kw):
        self._llamar("RemoveTagsFromResource", kw)
        for k in kw["TagKeys"]:
            self.params[kw["ResourceId"]]["tags"].pop(k, None)
        return {}

    def delete_parameters(self, **kw):
        self._llamar("DeleteParameters", kw)
        hechos = [n for n in kw["Names"] if n in self.params]
        for n in hechos:
            del self.params[n]
        return {"DeletedParameters": hechos, "InvalidParameters": [n for n in kw["Names"] if n not in hechos]}

    def get_parameter_history(self, **kw):
        self._llamar("GetParameterHistory", kw)
        n = kw["Name"]
        if n not in self.params:
            raise error("ParameterNotFound")
        self._leible(n)
        historia = self.params[n]["history"]
        inicio = int(kw.get("NextToken") or 0)
        pagina = historia[inicio:inicio + kw.get("MaxResults", 50)]
        r = {"Parameters": [{"Name": n, "Type": h["type"], "Value": h["value"], "Version": h["version"],
                             "Description": h["description"], "LastModifiedDate": h["modified"],
                             "LastModifiedUser": h["user"], "Labels": []} for h in pagina]}
        if inicio + len(pagina) < len(historia):
            r["NextToken"] = str(inicio + len(pagina))
        return r


class FakeSTS:
    def get_caller_identity(self):
        return {"Account": CUENTA, "Arn": f"arn:aws:iam::{CUENTA}:user/mario", "UserId": "AIDA"}


class FakeSesion:
    def __init__(self, ssm):
        self.ssm = ssm

    def client(self, servicio, region_name=None, config=None):
        return self.ssm if servicio == "ssm" else FakeSTS()


@pytest.fixture
def ssm():
    return FakeSSM()


CONFIG_EJEMPLO = '''## Mi configuración
# Un comentario que no se debe perder

perfiles = {
    "min": {"posicion_entorno": "inicio", "case_entorno": "lower", "case_ruta": "lower"},
    "max": {"posicion_entorno": "final", "case_entorno": "upper", "case_ruta": "ninguno"},
}

configuraciones = {
    "profile_name": "stan",
    "region_name": "eu-south-2",
    "entornos": ['dev', 'pre', 'prod'],
    "parameter_list": [
        {"path": "/app", "perfil": "min"},
        {"path": "/API/STA", "perfil": "max"},
    ]
}

perfil_nuevos = "min"  # el de los nuevos
tags_activas = True
obligatorias_vacias = False
tags_obligatorias = ["Application", "Environment"]
'''


@pytest.fixture
def config_path(tmp_path):
    ruta = tmp_path / "xsoft" / "paramsx_config.py"
    ruta.parent.mkdir()
    ruta.write_text(CONFIG_EJEMPLO, encoding="utf-8")
    return str(ruta)


TOKEN = "token-de-prueba"


@pytest.fixture
def cliente(ssm, config_path):
    """Cliente de Flask ya con la cookie del token y el Origin puesto."""
    from paramsx.web.app import crear_app
    app = crear_app(config_path=config_path, token=TOKEN, sesion_factory=lambda p, r: FakeSesion(ssm),
                    perfiles_aws=["default", "stan"])
    c = app.test_client()
    r = c.get(f"/?token={TOKEN}", base_url="http://127.0.0.1:8765")
    assert r.status_code == 302

    class Cliente:
        app_flask = app

        def get(self, url, **kw):
            return c.get(url, base_url="http://127.0.0.1:8765", **kw)

        def post(self, url, json=None, **kw):
            return c.post(url, json=json, base_url="http://127.0.0.1:8765",
                          headers={"Origin": "http://127.0.0.1:8765"}, **kw)

        def put(self, url, json=None, **kw):
            return c.put(url, json=json, base_url="http://127.0.0.1:8765",
                         headers={"Origin": "http://127.0.0.1:8765"}, **kw)

        crudo = c
    return Cliente()
