# ParamsX

ParamsX es una herramienta diseñada para gestionar y organizar parámetros de AWS SSM de manera sencilla y eficiente.

## ⚠ Breaking change en la versión 2.0.0

Si vienes de la 1.x tienes que **actualizar a mano tu `~/.xsoft/paramsx_config.py`**: `parameter_list` ya no es una lista de strings, ahora cada entrada es un diccionario con su convención de naming. La versión antigua **no es compatible** y ParamsX se niega a arrancar mostrando cómo migrarla. Detalle completo en el [CHANGELOG](CHANGELOG.md).

### Estructura Recomendada
La convención de naming es de 5 niveles, donde los últimos segmentos son opcionales según el caso:

```
/{entorno}/{servicio}/{nombre-servicio}/{servicio-adjunto}/{definición}
```

- `{entorno}`: SIEMPRE en minúscula (`dev`, `pre`, `prod`) y SIEMPRE el primer segmento, tanto en parámetros comunes como privados.
- `{servicio}`: la categoría. Puede ser `common` (lectura por defecto para todo el equipo) o el nombre real del servicio (`rds`, `api`, `email`...).
- `{definición}`: libre y descriptivo, no afecta a la lógica de permisos.

Ejemplos:
```
/dev/api/multiapi/bbdd
/dev/email/users
/dev/common/email/users
/dev/common/rds/cee-dev
/dev/rds/cee-dev/api/alertas-premium
/dev/api/alertas-premium/encryption_key
/dev/api/sta/auth/jwt_secret
```

Ventajas:
- Claridad: Fácil identificación de parámetros por entorno, servicio y componente.
- Escalabilidad: Crecimiento estructurado de la configuración.
- Permisos limpios: como el entorno va siempre en primera posición, `/{entorno}/common/*` es un prefijo puro y seguro para dar acceso de lectura por defecto a todo el equipo desde IAM. El acceso a los valores privados se controla por **tags** (ABAC), no por ruta.

#### Correlación de naming en RDS
En RDS, el segmento `{nombre-servicio}` del parámetro común debe coincidir **exactamente** con el del privado: es la clave que correlaciona `host/port/database` (común) con `user/password` (privado) al construir la conexión completa.

```
/dev/common/rds/cee-dev          -> host / port / database
/dev/rds/cee-dev/api/alertas     -> user / password
```

Al crear un parámetro con la opción 4, ParamsX comprueba que exista la contraparte y **avisa** si no la encuentra. Es solo un aviso: no bloquea la creación.

### ¿Cómo funciona?
Al ejecutar ```paramsx``` desde la terminal, accedes a un menú interactivo con estas opciones principales:

1. Leer parámetros
- Navega por la lista de parámetros configurada en tu archivo de configuración y selecciona cuál descargar.
- Elige el entorno deseado (por ejemplo, dev o prod).
- Archivos generados:
    - parameters_dev.py o parameters_prod.py → Edita estos archivos para modificar, añadir o eliminar parámetros (valores y tags).
    - parameters_dev_backup.py → Respaldo automático del archivo descargado, incluidas las tags.
Los archivos se crean en la misma ruta desde donde ejecutas paramsx, evitando movernos innecesariamente entre carpetas.
- Si tu rol IAM no tiene permisos sobre la ruta configurada, verás un mensaje claro en lugar de una traza de boto3:
```
⚠ No tienes permisos para leer: /dev/rds — pídele a un admin que te dé acceso, o acota
la ruta en tu parameter_list a algo más específico (ej. /dev/rds/<sub-ruta>).
```

2. Comparar y actualizar parámetros
- Una vez finalizados los ajustes en los parámetros descargados, selecciona esta opción.
- El programa pedirá el entorno correspondiente y realizará una comparación detallada, tanto de valores como de tags:
    - Nuevos: Parámetros que serán añadidos.
    - Modificados: Parámetros existentes cuyo valor y/o tags serán actualizados.
    - Eliminados: Parámetros que serán borrados de AWS.
Revisa los cambios antes de confirmar. Una vez completada la operación, los archivos temporales serán eliminados automáticamente para mantener el entorno limpio.

3. Crear backups
- Realiza copias de seguridad de los parámetros (valores y tags), eligiendo entre:
    - Parámetros de un entorno específico.
    - Todos los parámetros configurados en tu lista.
    - Opcional: Descarga de todos los parámetros almacenados en tu cuenta de AWS.
Esto te permitirá mantener respaldos seguros o realizar migraciones/reorganizaciones según sea necesario.

4. Crear nuevo parámetro
- Crea un parámetro desde cero sin salir de la herramienta. Te pedirá, en este orden:
    - La ruta completa, **siempre en convención `min`** (entorno primero y todo en minúscula: se fuerza automáticamente).
    - El valor: texto plano o JSON en una línea (por ejemplo `{"host": "x", "user": "y", "pass": "z"}`), que se valida antes de continuar.
    - Las tags obligatorias, si tienes `abac = True`.
- No se puede crear un parámetro nuevo con la convención `max`: esa convención existe solo para seguir leyendo y editando los paths legacy.
- Antes de subirlo verás una pantalla de confirmación con la ruta, el valor y las tags. El parámetro se crea con `Overwrite=False`, así que nunca machaca uno existente.
- Tras crearlo aparecerá la próxima vez que leas la ruta correspondiente de tu `parameter_list`.

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

```python
## Configuraciones ParamsX

configuraciones = {
    "profile_name": "default",           # Cambiar por el nombre de tu perfil en ~/.aws/credentials
    "region_name": "eu-south-2",         # Cambiar por tu región de AWS
    "entornos": ['dev', 'pre', 'prod'],  # SIEMPRE en minúscula, es la lista canónica única
    "parameter_list": [
        {"path": "/common", "convencion": "min"},
        {"path": "/rds", "convencion": "min"},
        {"path": "/api", "convencion": "min"},
        {"path": "/EMAIL", "convencion": "max"},
        {"path": "/API/STA", "convencion": "max"},
    ]
}

abac = True

obligatorias_vacias = False

tags_obligatorias = [
    "Application", "Environment", "Owner", "Project",
    "Product", "Service", "Component", "ManagedBy",
]
```
Nota: Si el archivo paramsx_config.py ya existe, no será sobrescrito durante la instalación para proteger las configuraciones personalizadas.

### La doble convención de naming: `min` y `max`

Durante la transición a la convención nueva conviven dos formas de construir la ruta. Cada entrada de `parameter_list` declara la suya, y **la diferencia no es solo el case: también cambia la posición donde se inserta el entorno**.

| convencion | Qué hace | Ejemplo con entorno `dev` |
|---|---|---|
| `min` | Convención nueva. Añade el entorno en **minúscula al principio** de la ruta. | `/rds` → `/dev/rds` |
| `max` | Convención legacy. Inserta el entorno en **mayúscula tras el primer segmento**. | `/API/STA` → `/API/DEV/STA` |
| `max` | Con un solo segmento queda al final. | `/EMAIL` → `/EMAIL/DEV` |

Ya **no existe** la lista `entornos_old`: el entorno en mayúscula de las rutas `max` se deriva con `.upper()` de la misma lista canónica `entornos`, que se escribe siempre en minúscula.

Ejemplo completo de una `parameter_list` migrada, mezclando rutas nuevas y legacy:

```python
    "parameter_list": [
        {"path": "/common", "convencion": "min"},
        {"path": "/rds", "convencion": "min"},
        {"path": "/api", "convencion": "min"},
        {"path": "/INFRA", "convencion": "max"},
        {"path": "/API/STA", "convencion": "max"},
        {"path": "/API/p15", "convencion": "max"},
        {"path": "/API/MULTIAPI", "convencion": "max"},
        {"path": "/APP/Alertas", "convencion": "max"},
        {"path": "/API/ALERTAS", "convencion": "max"},
        {"path": "/APP/Eter", "convencion": "max"},
        {"path": "/API/GIS", "convencion": "max"},
        {"path": "/API/PANGEA", "convencion": "max"},
        {"path": "/BUCKETS", "convencion": "max"},
        {"path": "/EMAIL", "convencion": "max"},
        {"path": "/INFERENCIAS/TASA_DMI", "convencion": "max"},
        {"path": "/IP", "convencion": "max"},
        {"path": "/TASA", "convencion": "max"},
        {"path": "/CEE/CEXGEN", "convencion": "max"},
    ]
```

Sobre mayúsculas y minúsculas: ParamsX **no renombra ni fuerza el case de los parámetros que ya existen**, los lee y edita tal cual estén según la convención que hayas indicado para esa ruta. Los parámetros **nuevos** que crea la herramienta (opción 4) van siempre en convención `min`.

### Cómo acotar tu parameter_list (recomendación)

`parameter_list` es solo tu vista de trabajo: **la seguridad real la impone IAM, no este fichero**. La recomendación de uso es:

- **Admins**: pueden configurar rutas raíz amplias, por ejemplo `{"path": "/rds", "convencion": "min"}` → `/dev/rds`.
- **Usuarios normales**: conviene acotar la ruta a lo que su rol IAM tiene realmente autorizado, por ejemplo `{"path": "/rds/cee-dev/api", "convencion": "min"}` → `/dev/rds/cee-dev/api`.

Si configuras una ruta más amplia que tus permisos, no pasa nada grave: ParamsX te avisará con un mensaje claro de acceso denegado en vez de una traza de boto3. Pero afinar la ruta te ahorra el error.

### Tags obligatorias y el flag `abac`

El control de acceso a los valores privados de la cuenta va por **tags IAM** (condición `aws:ResourceTag/${TagKey}` sobre `GetParameter`), no por restricción de path — la única excepción es `/{entorno}/common/*`, que se concede por prefijo de ruta. Por eso estas 8 tags son el mínimo no negociable: son las que sostienen todo el modelo ABAC de la cuenta AWS.

```
Application, Environment, Owner, Project, Product, Service, Component, ManagedBy
```

La lista vive en `tags_obligatorias`, dentro de tu propio `paramsx_config.py`, para poder ampliarla sin tocar código.

El flag `abac` decide si ParamsX gestiona tags:

- **`abac = True`**: al leer parámetros, el fichero exportado incluye un campo por tag con su valor actual en AWS (vacío si el parámetro es legacy y no la tiene). Al cargar, es **obligatorio** que las 8 tengan valor.
- **`abac = False`**: las tags no aparecen en el fichero exportado en absoluto y no se valida nada (comportamiento de la 1.x).

Formato del fichero exportado con `abac = True`:

```python
parametros = [
    {'parameter_name': '/dev/email/users',
     'parameter_value': """agpetrovici@stanalytics.es""",
     'tagApplication': "",
     'tagEnvironment': "",
     'tagOwner': "",
     'tagProject': "",
     'tagProduct': "",
     'tagService': "",
     'tagComponent': "",
     'tagManagedBy': "",
    },
]
```

Este formato con tags **solo existe en el fichero temporal que genera ParamsX**: no se ve en la consola de AWS ni se persiste en ningún otro sitio. Tiene el mismo ciclo de vida que el resto del fichero (se genera, se edita, se compara, se aplica y se borra al confirmar).

#### `obligatorias_vacias`: cuando alguna tag tiene que ir vacía

En la práctica hay parámetros a los que no les aplica alguna de las 8 tags. Ese caso se controla con `obligatorias_vacias`, y solo tiene efecto si `abac = True`:

| `obligatorias_vacias` | Comportamiento |
|---|---|
| `False` (por defecto) | Validación bloqueante: si a un parámetro le falta cualquiera de las tags obligatorias no se sube **ni su valor ni sus tags**. Al crear un parámetro tampoco te deja continuar dejando una tag en blanco. |
| `True` | Se permiten vacías: el parámetro se sube igualmente y **las tags sin valor no se crean en AWS** (no se suben como etiquetas vacías). En el informe de carga verás qué parámetros han quedado con tags vacías y cuáles son. |

Ojo con la diferencia entre "vacía" y "borrada": con `obligatorias_vacias = True`, una tag que se deja en blanco y **nunca existió** simplemente no se crea; pero si esa tag **ya tenía valor en AWS** y la vacías en el fichero, se interpreta como que quieres borrarla y se elimina del parámetro. Es la forma de quitar una tag.

Detalles del comportamiento con `abac = True`:

- La validación es **por parámetro**, no global: con `obligatorias_vacias = False`, si a uno le falta cualquiera de las 8 tags no se sube ni su valor ni sus tags, y verás un error indicando qué tags faltan y a qué `parameter_name`. El resto de parámetros del fichero que estén completos se suben con normalidad.
- Cuando una carga queda a medias, los ficheros `parameters_{entorno}.py` y su backup **no se borran**, para que corrijas lo que falta y vuelvas a cargar. El backup se resincroniza con lo ya aplicado, así que la segunda pasada solo sube lo que quedó pendiente.
- Si el parámetro ya existe y le faltan tags (creado antes de esta versión), se rellenan en este mismo flujo de edición, sin borrar ni recrear el parámetro.
- Los cambios de tags se aplican con `add_tags_to_resource` / `remove_tags_from_resource` en la misma pasada que el valor. Vaciar el campo de una tag en el fichero equivale a borrarla en AWS.
- Las tags de sistema (`aws:*`) no se exportan ni se tocan. Las tags que ya existan en AWS y no estén en la lista obligatoria se conservan y se pueden editar.
- No hay forma de saltarse la validación por parámetro salvo relajarla explícitamente en tu configuración con `obligatorias_vacias = True`, o desactivar las tags por completo con `abac = False`.

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
- Crear un parámetro nuevo.

### Leer Parámetros:
1. Selecciona la opción "Leer parámetros" en el menú. La lista muestra cada ruta con su convención, por ejemplo `/rds  [min]` o `/API/STA  [max]`.
2. Elige el prefijo y el entorno que deseas consultar.
3. Los parámetros serán descargados y guardados en archivos como:
    - parameters_dev.py
    - parameters_dev_backup.py
    ```Importante: Los archivos se generarán en la misma ruta desde donde ejecutes el comando paramsx```
4. Edita el archivo parameters_{entorno}.py con tu software favorito. Con `abac = True` cada parámetro trae además sus 8 campos de tag para rellenar.

### Cargar Parámetros:
1. Modifica los archivos generados (parameters_dev.py).
2. Usa la opción "Cargar parámetros desde archivo" para comparar los cambios.
3. El programa mostrará una lista con los siguientes estados:
    - Nuevos: Parámetros que se agregarán.
    - Modificados: Parámetros existentes que se actualizarán (valor, tags o ambos).
    - Eliminados: Parámetros que se eliminarán automáticamente de AWS SSM.
    * Revisa los cambios antes de confirmar.
    ```Importante: Una vez confirmados los cambios, los archivos parameters_dev.py y parameters_dev_backup.py se eliminarán automáticamente```
4. Si algún parámetro se queda sin subir por faltarle tags obligatorias, los ficheros se conservan para que lo corrijas y vuelvas a cargar.

### Crear un parámetro nuevo:
1. Selecciona la opción "Crear nuevo parámetro" y elige el entorno.
2. Escribe la ruta completa en convención `min` (`/dev/...`): se fuerza a minúscula y se valida que el primer segmento sea el entorno.
3. Escribe el valor: texto plano o JSON en una línea.
4. Rellena las tags obligatorias (si `abac = True`). `Environment` viene precargada con el entorno elegido. Con `obligatorias_vacias = True` puedes dejar alguna en blanco pulsando Enter: esas no se crearán en AWS.
5. Confirma en la pantalla de resumen. Si es un parámetro de RDS y falta su contraparte (común o privado), verás el aviso de correlación de naming ahí mismo.

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
    Los parámetros se manejan como SecureString para garantizar que la información sensible esté cifrada. Los permisos los impone IAM: `parameter_list` solo decide qué rutas intenta leer la herramienta.

- Errores:
    Los accesos denegados por IAM se muestran como un aviso legible. Cualquier otro error de AWS (ruta inexistente, throttling...) se propaga tal cual para que puedas diagnosticarlo.

- Modificar todos los parámetros actuales:
ParamsX ha sido diseñado para trabajar fácilmente con entornos y listas de parámetros bien organizados. Sin embargo, si necesitas realizar ajustes masivos a tus parámetros, puedes aprovechar la funcionalidad de backup completo para modificar y reorganizar todos tus parámetros cómodamente.

Pasos recomendados para modificar parámetros en masa:
1. Crea un backup completo:
    Usa la opción 3 del menú y selecciona "Todos los parámetros de AWS" para generar un archivo de respaldo con todos tus parámetros.
    El archivo generado será:
    - all_parameters_backup.py
2. Duplica y renombra el archivo:
    Cambia el nombre del archivo de backup para que quede acorde a tu entorno:
    - parameters_dev.py
    - parameters_dev_backup.py
3. Modifica los parámetros:
Edita el archivo parameters_dev.py según tus necesidades. Puedes añadir, modificar o eliminar parámetros según el entorno.
4. Carga los nuevos parámetros:
Selecciona la opción "Cargar parámetros desde archivo" y elige el entorno dev.
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