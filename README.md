# ParamsX

ParamsX es una librería diseñada para gestionar parámetros de AWS SSM de manera sencilla y eficiente. Con ella podrás:
- Leer parámetros almacenados en AWS SSM.
- Comparar y actualizar parámetros existentes.
- Eliminar parámetros que ya no estén presentes en los archivos de configuración.
- Crear respaldos para evitar pérdida de datos.


#### Consejos varios para tener un orden en los parámetros
Para aprovechar al máximo ParamsX, te recomendamos estructurar los parámetros de AWS SSM siguiendo un esquema lógico y ordenado. Por ejemplo:
- /APP/nombreApp/tipoEntorno/más datos...

Ventajas de usar esta estructura:
- Claridad: Es más sencillo identificar a qué aplicación, entorno o componente pertenece cada parámetro.
- Escalabilidad: Facilita el crecimiento de tu infraestructura manteniendo un orden consistente.
- Gestión simplificada: Con ParamsX, puedes configurar listas específicas de parámetros basadas en estos prefijos, lo que permite modificarlos o gestionarlos de forma eficiente.

Este enfoque te permitirá integrar ParamsX de manera más efectiva en tu flujo de trabajo y mantener el control de tus parámetros en AWS SSM.

## Instalación

```pip install paramx```

### Configuración inicial
Una vez instalado el paquete, debes configurar ParamsX antes de usarlo. Para ello, ejecuta el siguiente comando:
``` paramsx configure ```

Este comando creará automáticamente una carpeta de configuración en tu directorio de usuario:

Windows: C:\Users\<tu_usuario>\.xsoft
Linux/MacOS: /home/<tu_usuario>/.xsoft

Dentro de esta carpeta encontrarás un archivo llamado paramsx_config.py. 
Este archivo contiene la configuración inicial de la librería. Antes de usarla, debes asegurarte de editar este archivo para incluir el perfil de AWS y la región que utilizarás.

Contenido de paramsx_config.py:

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


## Modo de Uso
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

### Modificar parámetros actuales
Un pequeño truco para modificar tus parámetros actuales:
1. Crea los archivos necesarios:
    - parameters_DEV.py (Cambia DEV por el entorno deseado)
    - parameters_DEV_backup.py (Cambia DEV por el entorno deseado)
2. Copia tus parámetros dentro de cada uno de ellos.
3. Modifica los en el archivo parameters_DEV.py
4. Accede a paramsx y usa la opción 2 de cargar seleccionando el entorno.
5. Verás tus parametros nuevos, modificados y los que se eliminarán.

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
Ten en cuenta que este proceso puede tardar dependiendo de la cantidad de parámetros almacenados.

### Notas Adicionales
- Credenciales de AWS:
    Asegúrate de que el perfil especificado en paramsx_config.py exista en tus archivos de configuración de AWS (~/.aws/credentials y ~/.aws/config).

- Seguridad:
    Los parámetros se manejan como SecureString para garantizar que la información sensible esté cifrada

- Backup:
    Antes de realizar cualquier cambio, ParamsX crea automáticamente un respaldo (parameters_DEV_backup.py). Este archivo se eliminará después de cargar los nuevos parámetro

## Licencia
ParamsX se distribuye bajo la licencia MIT. Puedes usarlo libremente, modificarlo y adaptarlo a tus necesidades. Recuerda siempre hacer un respaldo de tus configuraciones antes de realizar cambios.
```Nota: El creador de ParamsX no se hace responsable de posibles pérdidas de datos o configuraciones incorrectas.```