from setuptools import setup, find_packages
from setuptools.command.install import install
from distutils import log
import os
import sys
import shutil
import platform

class CustomInstallCommand(install):
    def run(self):
        # Ejecutar instalación predeterminada
        install.run(self)

        # 1. Agregar directorio de scripts al PATH
        self._add_scripts_to_path()

    def _add_scripts_to_path(self):
        """Añadir directorio de scripts al PATH del sistema."""
        system = platform.system()
        scripts_dir = None

        if system == "Windows":
            scripts_dir = os.path.join(
                os.path.expanduser("~"),
                "AppData",
                "Roaming",
                "Python",
                f"Python{sys.version_info.major}{sys.version_info.minor}",
                "Scripts",
            )
        elif system in ["Linux", "Darwin"]:  # Linux o macOS
            scripts_dir = os.path.join(os.path.dirname(sys.executable), "bin")

        if scripts_dir:
            path_env = os.environ.get("PATH", "")
            if scripts_dir not in path_env:
                if system == "Windows":
                    os.system(f'setx PATH "{path_env};{scripts_dir}"')
                    print(f"Se agregó {scripts_dir} al PATH. Reinicia tu terminal para que los cambios surtan efecto.")
                elif system in ["Darwin", "Linux"]:
                    shell_config = "~/.zshrc" if system == "Darwin" else "~/.bashrc"
                    self._add_to_shell_config(shell_config, scripts_dir)

        else:
            sys.stderr.write(
                        f"No se pudo agregar {scripts_dir} al PATH. "
                        f"Añádelo manualmente para poder ejecutar paramsx sin complicaciones.\n"
                        f"En Windows: Ve al 'Panel de control', busca 'variables de entorno', "
                        f"y edita las 'Variables de usuario' para agregar este path.\n"
                        f"En Linux/Mac: Edita tu archivo de shell (~/.bashrc o ~/.zshrc) y agrega:\n"
                        f'export PATH="{scripts_dir}:$PATH".'
                    )

    def _add_to_shell_config(self, shell_config, scripts_dir):
        """Añadir el directorio de scripts al archivo de configuración del shell."""
        shell_config = os.path.expanduser(shell_config)
        export_line = f'export PATH="{scripts_dir}:$PATH"'

        try:
            if os.path.exists(shell_config):
                with open(shell_config, "a") as f:
                    f.write(f"\n{export_line}\n")
                print(f"Se agregó {scripts_dir} a {shell_config}.")
            else:
                with open(shell_config, "w") as f:
                    f.write(f"{export_line}\n")
                print(f"Se creó {shell_config} y se agregó {scripts_dir}.")
        except Exception as e:
            print(f"Error al actualizar el archivo de shell {shell_config}: {e}")


## Leer Readme para asociarlo a Pypi
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

# Configuración del paquete
setup(
    name="paramsx",
    version="1.1.3",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "paramsx": ["paramsx_config.py"],  # Asegúrate de incluir este archivo
    },
    install_requires= [
        "boto3",
        "windows-curses; platform_system == 'Windows'",
    ],
    entry_points={
        "console_scripts": [
            "paramsx=paramsx.main:entry_point",
        ],
    },
    cmdclass={
        "install": CustomInstallCommand,
    },
    description="Librería para gestionar y respaldar parámetros de AWS SSM de manera sencilla y eficiente.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Mariox",
    author_email="info@tomonota.net",
    url="https://github.com/pistatxos/paramsx",
)
