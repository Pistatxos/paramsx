"""Perfiles, rutas y configuración: lo que comparten la terminal y la web."""
import pytest

from paramsx.core import config as core_config
from paramsx.core.rutas import aplicar_case_ruta, build_full_path, grupo_desde_carpeta

from conftest import CONFIG_EJEMPLO

PERFILES = {
    "min": {"posicion_entorno": "inicio", "case_entorno": "lower", "case_ruta": "lower"},
    "max": {"posicion_entorno": "final", "case_entorno": "upper", "case_ruta": "ninguno"},
    "mixto_max": {"posicion_entorno": "mixto", "case_entorno": "upper", "case_ruta": "ninguno"},
}


@pytest.mark.parametrize("ruta, perfil, esperado", [
    ("/rds", "min", "/dev/rds"),
    ("/API/STA", "max", "/API/STA/DEV"),
    ("/API/*/STA", "mixto_max", "/API/DEV/STA"),
])
def test_build_full_path(ruta, perfil, esperado):
    assert build_full_path(ruta, PERFILES[perfil], "dev") == esperado


def test_case_ruta():
    assert aplicar_case_ruta("/Mi-App/clave", "capitalize") == "/Mi-app/Clave"
    assert aplicar_case_ruta("/Mi-App/clave", "ninguno") == "/Mi-App/clave"


@pytest.mark.parametrize("carpeta, path, perfil", [
    ("/dev/rds/cee", "/rds/cee", "min"),               # 1er segmento -> inicio
    ("/API/STA/DEV", "/API/STA", "max"),               # último -> final, en MAYÚSCULAS
    ("/API/MULTIAPI/DEV/stan_ai", "/API/MULTIAPI/*/stan_ai", "mixto_max"),  # en medio -> mixto
])
def test_grupo_desde_carpeta_usa_perfil_existente(carpeta, path, perfil):
    entrada, nuevo = grupo_desde_carpeta(carpeta, ["dev", "pre", "prod"], PERFILES)
    assert entrada["path"] == path and entrada["perfil"] == perfil and nuevo is None


def test_grupo_desde_carpeta_crea_perfil_si_no_encaja():
    entrada, nuevo = grupo_desde_carpeta("/Dev/app", ["dev"], PERFILES)
    assert entrada == {"nombre": "app", "path": "/app", "perfil": "inicio_capitalize"}
    assert nuevo == ("inicio_capitalize", {"posicion_entorno": "inicio", "case_entorno": "capitalize",
                                          "case_ruta": "ninguno"})
    entrada, nuevo = grupo_desde_carpeta("/tools/x", ["dev"], PERFILES)
    assert entrada["perfil"] == "ninguno" and nuevo[1]["posicion_entorno"] == "ninguno"


def test_grupo_desde_carpeta_solo_entorno():
    with pytest.raises(ValueError):
        grupo_desde_carpeta("/dev", ["dev"], PERFILES)


def test_lectura_literal_igual_que_la_terminal(tmp_path, monkeypatch):
    """La web lee el fichero sin ejecutarlo y obtiene lo mismo que la terminal ejecutándolo."""
    from paramsx import main
    ruta = tmp_path / "c.py"
    ruta.write_text(CONFIG_EJEMPLO)
    monkeypatch.setattr(main, "CONFIG_PATH", str(ruta))
    assert core_config.cargar_config_literal(str(ruta)) == main.load_config()


def test_nombres_antiguos(tmp_path):
    ruta = tmp_path / "c.py"
    ruta.write_text('''naming = {"min": {"posicion_entorno": "inicio"}}
configuraciones = {"profile_name": "a", "region_name": "b", "entornos": ["dev"],
                   "parameter_list": [{"path": "/x", "convencion": "min"}]}
convencion_nuevos = "min"
abac = False
''')
    cfg = core_config.cargar_config_literal(str(ruta))
    assert cfg["perfiles"] == {"min": {"posicion_entorno": "inicio"}}
    assert cfg["perfil_nuevos"] == "min" and cfg["tags_activas"] is False
    assert core_config.validate_config(cfg) == ([], [])


def test_no_ejecuta_ni_acepta_codigo(tmp_path):
    ruta = tmp_path / "c.py"
    ruta.write_text('import os\nconfiguraciones = {"profile_name": os.environ["X"]}\n')
    with pytest.raises(core_config.ConfigNoLegible):
        core_config.cargar_config_literal(str(ruta))


def test_guardar_conserva_comentarios_y_lo_lee_la_terminal(config_path, monkeypatch):
    from paramsx import main
    cfg = core_config.cargar_config_literal(config_path)
    cfg["parameter_list"].append({"nombre": "Base de datos", "path": "/rds", "perfil": "min"})
    cfg["entornos"] = ["dev", "stg", "prod"]
    core_config.guardar_config(cfg, config_path)

    texto = open(config_path).read()
    assert "# Un comentario que no se debe perder" in texto
    assert "# el de los nuevos" in texto                     # comentario de detrás de la línea
    assert '{"nombre": "Base de datos", "path": "/rds", "perfil": "min"},  # -> /dev/rds' in texto
    assert open(config_path + ".bak").read() == CONFIG_EJEMPLO

    monkeypatch.setattr(main, "CONFIG_PATH", config_path)
    leida = main.load_config()                               # la terminal lo ejecuta
    assert leida == core_config.cargar_config_literal(config_path)
    assert leida["entornos"] == ["dev", "stg", "prod"]
    assert core_config.validate_config(leida) == ([], [])
    # La terminal ignora el nombre del grupo
    assert core_config.normalize_config(leida)["parameter_list"][-1] == {"path": "/rds", "perfil": "min"}


def test_guardar_cambia_nombres_antiguos(tmp_path):
    ruta = tmp_path / "c.py"
    ruta.write_text('''naming = {"min": {"posicion_entorno": "inicio", "case_entorno": "lower", "case_ruta": "ninguno"}}
configuraciones = {"profile_name": "a", "region_name": "b", "entornos": ["dev"],
                   "parameter_list": [{"path": "/x", "convencion": "min"}], "otra": 1}
abac = True
''')
    cfg = core_config.cargar_config_literal(str(ruta))
    cfg["parameter_list"] = [{"path": "/x", "perfil": "min"}]
    core_config.guardar_config(cfg, str(ruta))
    valores, _ = core_config.leer_asignaciones(ruta.read_text())
    assert "naming" not in valores and "abac" not in valores
    assert valores["perfiles"] == cfg["perfiles"] and valores["tags_activas"] is True
    assert valores["configuraciones"]["otra"] == 1           # lo que la web no gestiona se conserva


def test_guardar_sin_fichero_parte_de_la_plantilla(tmp_path):
    ruta = tmp_path / "nuevo" / "paramsx_config.py"
    cfg = core_config.config_plantilla()
    cfg["profile_name"] = "mio"
    core_config.guardar_config(cfg, str(ruta))
    texto = ruta.read_text()
    assert "posicion_entorno  | inicio | final | mixto | ninguno" in texto  # la tabla de la plantilla
    assert core_config.cargar_config_literal(str(ruta))["profile_name"] == "mio"
