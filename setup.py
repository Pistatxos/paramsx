from setuptools import setup, find_packages
import re

# Sin orden de instalación propia: pip crea el comando «paramsx» (entry_points) y el PATH se explica en el README.
# Antes se añadía una línea al ~/.zshrc o ~/.bashrc, también al construir el paquete (python -m build).

## Leer Readme para asociarlo a Pypi
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

## La versión vive en paramsx/__init__.py, para que 'paramsx --version' y el paquete
## no puedan decir cosas distintas. Se lee con regex para no importar el paquete aquí.
with open("paramsx/__init__.py", "r", encoding="utf-8") as fh:
    version = re.search(r'^__version__\s*=\s*"([^"]+)"', fh.read(), re.M).group(1)

# Configuración del paquete
setup(
    name="paramsx",
    version=version,
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "paramsx": ["paramsx_config.py"],  # Asegúrate de incluir este archivo
        "paramsx.web": ["templates/*.html", "static/*"],
    },
    install_requires= [
        "boto3",
        "windows-curses; platform_system == 'Windows'",
        "flask>=2.2",  # la versión web
    ],
    # 'paramsx[web]' se mantiene para quien lo instaló así en la 2.4.0; ya no añade nada
    extras_require={
        "web": [],
    },
    entry_points={
        "console_scripts": [
            "paramsx=paramsx.main:entry_point",
        ],
    },
    description="Librería para gestionar y respaldar parámetros de AWS SSM de manera sencilla y eficiente.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Mariox",
    author_email="info@tomonota.net",
    url="https://github.com/pistatxos/paramsx",
)
