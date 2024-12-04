# ParamsX

ParamsX es una herramienta diseñada para gestionar y organizar parámetros de AWS SSM de manera sencilla y eficiente.

### Estructura Recomendada
Organiza los parámetros en AWS SSM con un esquema claro y ordenado:
"/APP/nombreApp/tipoEntorno/dato"

Ejemplo:
/APP/gestorClientes/DEV/grupos
/APP/gestorClientes/PROD/grupos

Ventajas:
- Claridad: Fácil identificación de parámetros por grupo y entorno.
- Escalabilidad: Crecimiento estructurado de la configuración.

Al registrar en la configuración de ParamsX los parámetros tipo: "/APP/gestorClientes" aprovechamos esta estructura para buscar y gestionar parámetros de forma eficiente.

### ¿Cómo funciona?
Al ejecutar ```paramsx``` desde la terminal, accedes a un menú interactivo con estas opciones principales:

1. Leer parámetros
- Navega por la lista de parámetros configurada en tu archivo de configuración y selecciona cuál descargar.
- Elige el entorno deseado (por ejemplo, DEV o PROD).
- Archivos generados:
    - parameters_DEV.py o parameters_PROD.py → Edita estos archivos para modificar, añadir o eliminar parámetros.
    - parameters_DEV_backup.py → Respaldo automático del archivo descargado.
Los archivos se crean en la misma ruta desde donde ejecutas paramsx, evitando movernos innecesariamente entre carpetas.

2. Comparar y actualizar parámetros
- Una vez finalizados los ajustes en los parámetros descargados, selecciona esta opción.
- El programa pedirá el entorno correspondiente y realizará una comparación detallada:
    - Nuevos: Parámetros que serán añadidos.
    - Modificados: Parámetros existentes que serán actualizados.
    - Eliminados: Parámetros que serán borrados de AWS.
Revisa los cambios antes de confirmar. Una vez completada la operación, los archivos temporales serán eliminados automáticamente para mantener el entorno limpio.

3. Crear backups
- Realiza copias de seguridad de los parámetros, eligiendo entre:
    - Parámetros de un entorno específico.
    - Todos los parámetros configurados en tu lista.
    - Opcional: Descarga de todos los parámetros almacenados en tu cuenta de AWS.
Esto te permitirá mantener respaldos seguros o realizar migraciones/reorganizaciones según sea necesario.

### Requisitos
ParamsX utiliza boto3 para interactuar con AWS. Asegúrate de tener configuradas tus credenciales de AWS antes de usarlo.

Te interesa? pues sigue leyendo y explico como instalarlo.


## Instalación

Para instalar ParamsX, utiliza el comando:

```pip install paramx```

### Configuración inicial
Después de instalar el paquete, es necesario configurarlo antes de usarlo. Ejecuta:

``` paramsx configure ```

Este comando creará automáticamente una carpeta de configuración en tu directorio de usuario:

- Windows: C:\Users\<tu_usuario>\.xsoft
- Linux/MacOS: /home/<tu_usuario>/.xsoft

Dentro de esta carpeta, encontrarás el archivo paramsx_config.py. Este archivo contiene la configuración inicial que debes ajustar según tu entorno.

Ejemplo del contenido de paramsx_config.py:

```
configuraciones = {
    "profile_name": "default",  # Cambiar por el nombre de tu perfil en ~/.aws/credentials
    "region_name": "eu-south-2",  # Cambiar por tu región de AWS
    "entornos": ["DEV", "PROD"],  # Los entornos que manejarás
    "parameter_list": [ # Cambiar por lista de parámetros.
        "/params1/xx",
        "/params2/xx",
    ]
}
```
Nota: Si el archivo paramsx_config.py ya existe, no será sobrescrito durante la instalación para proteger las configuraciones personalizadas.

#### Configuración manual del PATH
En algunos sistemas (especialmente en entornos corporativos como Windows), el PATH puede no configurarse automáticamente durante la instalación. Si ocurre esto, sigue los pasos según tu sistema operativo:

- En Windows
1. Ve al Panel de control y busca: Editar las variables de usuario para <tu_usuario>.
2. Añade una nueva entrada en las variables de usuario con el siguiente valor:
```C:\Users\<tu_usuario>\AppData\Roaming\Python\Python<versión>\Scripts``` 
(Reemplaza <tu_usuario> por tu nombre de usuario y <versión> por la versión de Python, como 312 para Python 3.12).
3. Guarda los cambios y reinicia tu terminal.

- En Linux/MacOS
1. Abre tu terminal y edita el archivo de configuración de tu shell:
    - Para bash: ~/.bashrc
    - Para zsh: ~/.zshrc
2. Añade la siguiente línea al final del archivo:
```export PATH="$HOME/.local/bin:$PATH"```
3. Guarda los cambios y recarga la configuración del shell ejecutando:
```source ~/.bashrc   # Para bash```
```source ~/.zshrc    # Para zsh```

Una vez instalado, verifica que el comando paramsx esté disponible ejecutando:
```paramsx --help```


## Modo de empleo
Ejecuta el comando principal desde la terminal:

```paramsx```

Navega por el menú interactivo:

El programa mostrará un menú donde Podrás:
- Leer parámetros desde AWS SSM.
- Cargar y actualizar parámetros.
- Backup de parámetros.

### Leer Parámetros:
1. Selecciona la opción "Leer parámetros" en el menú.
2. Elige el prefijo y el entorno que deseas consultar.
3. Los parámetros serán descargados y guardados en archivos como:
    - parameters_DEV.py
    - parameters_DEV_backup.py
    ```Importante: Los archivos se generarán en la misma ruta desde donde ejecutes el comando paramsx```
4. Edita el archivo parameters_{entorno}.py con tu software favorito.

### Cargar Parámetros:
1. Modifica los archivos generados (parameters_DEV.py).
2. Usa la opción "Cargar parámetros desde archivo" para comparar los cambios.
3. El programa mostrará una lista con los siguientes estados:
    - Nuevos: Parámetros que se agregarán.
    - Modificados: Parámetros existentes que se actualizarán.
    - Eliminados: Parámetros que se eliminarán automáticamente de AWS SSM.
    * Revisa los cambios antes de confirmar.
    ```Importante: Una vez confirmados los cambios, los archivos parameters_DEV.py y parameters_DEV_backup.py se eliminarán automáticamente```

### Backup Parámetros:
1. Backup de un rango específico:
Selecciona un prefijo y un entorno específico.
Se creará un archivo único con el respaldo de los parámetros de esa selección.
Ideal para respaldar y modificar parámetros de una aplicación o entorno en particular.
2. Backup de todos los parámetros listados:
Genera un respaldo combinado de todos los prefijos definidos en tu configuración (parameter_list) y sus entornos asociados.
Se crea un archivo total_listed_parameters_backup.py que contiene los parámetros organizados.
3. Backup de todos los parámetros de la cuenta de AWS:
Lee todos los parámetros de AWS SSM desde la raíz (/).
Se crea un archivo all_parameters_backup.py con el respaldo completo de la cuenta.
Nota: Este proceso puede tardar dependiendo de la cantidad de parámetros almacenados.


### Notas Adicionales
- Seguridad:
    Los parámetros se manejan como SecureString para garantizar que la información sensible esté cifrada

- Modificar todos los parámetros actuales:
ParamsX ha sido diseñado para trabajar fácilmente con entornos y listas de parámetros bien organizados. Sin embargo, si necesitas realizar ajustes masivos a tus parámetros, puedes aprovechar la funcionalidad de backup completo para modificar y reorganizar todos tus parámetros cómodamente.

Pasos recomendados para modificar parámetros en masa:
1. Crea un backup completo:
    Usa la opción 3 del menú y selecciona "Todos los parámetros de AWS" para generar un archivo de respaldo con todos tus parámetros.
    El archivo generado será:
    - all_parameters_backup.py
2. Duplica y renombra el archivo:
    Cambia el nombre del archivo de backup para que quede acorde a tu entorno:
    - parameters_DEV.py
    - parameters_DEV_backup.py
3. Modifica los parámetros:
Edita el archivo parameters_DEV.py según tus necesidades. Puedes añadir, modificar o eliminar parámetros según el entorno.
4. Carga los nuevos parámetros:
Selecciona la opción "Cargar parámetros desde archivo" y elige el entorno DEV.
5. Revisa los cambios:
    El programa te mostrará una lista detallada de los cambios:
    - Nuevos: Parámetros que se agregarán.
    - Modificados: Parámetros existentes que serán actualizados.
    - Eliminados: Parámetros que se eliminarán de AWS SSM.
6. Confirma la carga:
Una vez revisados los cambios, confirma para aplicar los ajustes en AWS SSM.


## Licencia
ParamsX se distribuye bajo la licencia MIT, lo que significa que puedes usarlo libremente, modificarlo y adaptarlo a tus necesidades.
```Nota: No hay responsabilidad alguna en posibles pérdidas de datos o configuraciones incorrectas. Por favor, asegúrate de revisar cuidadosamente los cambios antes de confirmarlos.```