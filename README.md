# ParamsX

ParamsX es una herramienta diseñada para gestionar y organizar parámetros de AWS SSM de manera sencilla y eficiente.

## ⚠ Breaking change en la versión 2.0.0

Si vienes de la 1.x tienes que **actualizar a mano tu `~/.xsoft/paramsx_config.py`**: `parameter_list` ya no es una lista de strings, ahora cada entrada es un diccionario que declara su perfil. La versión antigua **no es compatible** y ParamsX se niega a arrancar mostrando cómo migrarla. Detalle completo en el [CHANGELOG](CHANGELOG.md).

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
- El programa te muestra **los ficheros que tienes en el directorio** listos para cargar (los que conservan su backup al lado) y eliges cuál. No te pregunta por rutas ni entornos: el fichero ya sabe de dónde salió.
- Con el elegido hace una comparación detallada, tanto de valores como de tags:
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
    - La ruta **sin el entorno**, igual que la declaras en `parameter_list`: el perfil se encarga de colocarlo. Verás en pantalla la ruta resultante en AWS antes de seguir.
    - El valor: texto plano o JSON en una línea (por ejemplo `{"host": "x", "user": "y", "pass": "z"}`), que se valida antes de continuar.
    - Las tags obligatorias, si tienes `tags_activas = True`.
- El perfil que se usa es el que declares en `perfil_nuevos`. Si tu perfil es de tipo `mixto`, escribe el `*` en la ruta para indicar dónde va el entorno.
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

Si ya tenías configuración de una versión anterior, `paramsx configure` **no la sobrescribe**: te dice qué opciones nuevas no tienes y con qué valor por defecto se están rellenando, y si la configuración es válida. Con `paramsx configure --ejemplo` además deja la plantilla de esta versión en `paramsx_config.ejemplo.py`, al lado de la tuya, para que compares sin tocar nada.

Ejemplo del contenido de paramsx_config.py:

```python
## Configuraciones ParamsX

# --- Perfiles -------------------------------------------------------------
# Un perfil dice CÓMO se construye la ruta real en AWS a partir de la ruta que declaras
# en 'parameter_list' y del entorno que eliges en el menú. Los nombres son tuyos: define
# solo los que uses y llámalos como quieras. Un perfil tiene tres campos:
#
#   campo             | valores                                  | qué decide
#   ------------------+------------------------------------------+---------------------------
#   posicion_entorno  | inicio | final | mixto | ninguno          | dónde va el entorno
#   case_entorno      | lower | upper | capitalize                | cómo se escribe el entorno
#   case_ruta         | lower | upper | capitalize | ninguno      | case de la ruta AL CREAR
#
# posicion_entorno -> dónde se coloca el entorno (ejemplos con el entorno 'dev'):
#
#   valor    | ruta declarada  | ruta real en AWS
#   ---------+-----------------+--------------------------------------------------------
#   inicio   | /rds            | /dev/rds
#   final    | /API/STA        | /API/STA/DEV
#   mixto    | /API/*/STA      | /API/DEV/STA    el '*' marca el sitio; uno y como segmento
#   ninguno  | /api/sta/auth   | /api/sta/auth   una cuenta AWS por entorno; case_entorno da igual
#
# case_entorno -> cómo se escribe ese entorno en la ruta:
#
#   valor       | 'dev' se escribe | ruta real de /API/STA con posicion_entorno=final
#   ------------+------------------+------------------------------------------------
#   lower       | dev              | /API/STA/dev
#   upper       | DEV              | /API/STA/DEV
#   capitalize  | Dev              | /API/STA/Dev
#
# case_ruta -> a qué case se fuerza la ruta que TÚ escribes al CREAR un parámetro
# (opción 4 del menú). No afecta a leer ni a editar: lo que ya existe en AWS se
# respeta siempre tal cual esté.
#
#   valor       | si escribes /API/MULTIAPI/Token, se crea
#   ------------+-----------------------------------------
#   lower       | /api/multiapi/token
#   upper       | /API/MULTIAPI/TOKEN
#   capitalize  | /Api/Multiapi/Token
#   ninguno     | /API/MULTIAPI/Token
#
# Combina los tres campos como necesites: no hay una lista cerrada de perfiles. En el
# README tienes más ejemplos.

perfiles = {
    "min": {"posicion_entorno": "inicio", "case_entorno": "lower", "case_ruta": "lower"},
    "max": {"posicion_entorno": "final", "case_entorno": "upper", "case_ruta": "ninguno"},
    "mixto_max": {"posicion_entorno": "mixto", "case_entorno": "upper", "case_ruta": "ninguno"},
    # Crea los tuyos combinando los valores de la tabla, por ejemplo:
    # "sin_entorno": {"posicion_entorno": "ninguno", "case_entorno": "lower", "case_ruta": "ninguno"},
}

configuraciones = {
    "profile_name": "default",           # Cambiar por el nombre de tu perfil en ~/.aws/credentials
    "region_name": "eu-south-2",         # Cambiar por tu región de AWS
    "entornos": ['dev', 'pre', 'prod'],  # SIEMPRE en minúscula, es la lista canónica única
    "parameter_list": [
        {"path": "/common", "perfil": "min"},      # -> /dev/common
        {"path": "/rds", "perfil": "min"},         # -> /dev/rds
        {"path": "/EMAIL", "perfil": "max"},       # -> /EMAIL/DEV
        {"path": "/API/STA", "perfil": "max"},     # -> /API/STA/DEV
        # Con 'mixto' acotas por debajo del entorno: esto lee solo stan_ai, en vez de
        # todo lo que cuelga de /API/MULTIAPI/DEV
        {"path": "/API/MULTIAPI/*/stan_ai", "perfil": "mixto_max"},  # -> /API/MULTIAPI/DEV/stan_ai
    ]
}

# Perfil que se usa al crear un parámetro nuevo (opción 4 del menú).
# Si no lo defines, se usa el primero de 'perfiles'.
perfil_nuevos = "min"

# ¿El nombre del fichero exportado incluye la ruta leída?
#   False -> parameters_dev.py            (comportamiento de siempre)
#   True  -> parameters_dev__API_STA__max.py  (uno por entrada y entorno: lleva el
#            entorno, la ruta y el perfil, porque dos entradas pueden compartir ruta)
# Ponlo en True si sueles leer varias rutas del mismo entorno y no quieres que la
# segunda lectura te machaque el fichero de la primera.
fichero_por_ruta = False


## Configuraciones Tags

# Gestionar las tags de los parámetros: leerlas de AWS, exponerlas en el fichero
# exportado para editarlas y validar las obligatorias al cargar.
#   True  -> las tags viajan en el fichero y se validan.
#   False -> no aparecen tags en el fichero y no se valida nada.
# En cuentas cuyo control de acceso va por tags (ABAC vía IAM) esto debe estar en True.
tags_activas = True

# Solo aplica si tags_activas = True.
#   False -> validación bloqueante: si a un parámetro le falta alguna tag obligatoria
#            no se sube (ni su valor ni sus tags).
#   True  -> se permiten vacías: el parámetro se sube igualmente y las tags sin valor
#            simplemente NO se crean en AWS (no se suben como etiquetas vacías).
obligatorias_vacias = False

# Tags que se exigen en cada parámetro cuando tags_activas = True. La lista es libre:
# estas 8 son las que sostienen el control de acceso ABAC vía IAM de nuestra cuenta.
tags_obligatorias = [
    "Application",
    "Environment",
    "Owner",
    "Project",
    "Product",
    "Service",
    "Component",
    "ManagedBy",
]
```
Nota: Si el archivo paramsx_config.py ya existe, no será sobrescrito durante la instalación para proteger las configuraciones personalizadas.

### Los perfiles

Cada organización nombra sus parámetros a su manera, así que ParamsX no impone ninguna convención: **tú defines los perfiles que uses en el diccionario `perfiles` y les pones el nombre que quieras**. Cada entrada de `parameter_list` declara con qué perfil se construye su ruta completa, con la clave `perfil`. Los tres campos de un perfil y sus valores están explicados en el propio fichero de configuración, ahí arriba.

**No hay una lista cerrada de perfiles.** Los tres campos se combinan libremente, así que la plantilla no intenta traértelos todos: define los dos o tres que use tu organización y olvídate del resto. `min` y `max` vienen predefinidos porque son los que ParamsX traía antes de que los perfiles fueran configurables.

**Para qué sirve el `*`.** Además de colocar el entorno donde quieras, acota la lectura a un solo subárbol: con `/API/MULTIAPI/*/stan_ai` lees únicamente `/API/MULTIAPI/DEV/stan_ai`, en vez de todo lo que cuelga de `/API/MULTIAPI/DEV`. Debe ser un segmento entero, aparecer **exactamente una vez** y solo se admite en perfiles `mixto`: si el perfil y la ruta no cuentan la misma historia, ParamsX te lo dice al arrancar en vez de leer una ruta inexistente y devolverte una lista vacía.

**Los entornos.** Ya no existe la lista `entornos_old`: el entorno sale siempre de la lista canónica `entornos` (en minúscula), aplicándole el `case_entorno` del perfil. Si en tus rutas se llama `staging` en vez de `pre`, ponlo así en `entornos`.

Y ParamsX **no renombra ni fuerza el case de los parámetros que ya existen**: los lee y edita tal cual estén. El `case_ruta` del perfil solo entra en juego al crear parámetros nuevos.

### Un fichero por ruta: `fichero_por_ruta`

Al leer una ruta se generan `parameters_{entorno}.py` y su backup. Ese nombre depende solo del entorno, así que si lees una segunda ruta del mismo entorno **machacas el fichero de la primera**. Por defecto ParamsX te avisa y te pide confirmación antes de sobrescribir.

Si trabajas a menudo con varias rutas del mismo entorno, pon `fichero_por_ruta = True`: cada entrada pasa a tener su propio fichero y dejan de pisarse. Al cargar los verás todos en la lista y eliges cuál aplicar.

En el nombre van el entorno, la ruta y el perfil, porque dos entradas pueden compartir la ruta declarada y apuntar a sitios distintos:

| Entrada | Fichero |
|---|---|
| `{"path": "/API/STA", "perfil": "max"}` | `parameters_dev__API_STA__max.py` |
| `{"path": "/API/*/STA", "perfil": "mixto_max"}` | `parameters_dev__API_env_STA__mixto_max.py` |

### Cómo acotar tu parameter_list (recomendación)

`parameter_list` es solo tu vista de trabajo: **la seguridad real la impone IAM, no este fichero**. La recomendación de uso es:

- **Admins**: pueden configurar rutas raíz amplias, por ejemplo `{"path": "/rds", "perfil": "min"}` → `/dev/rds`.
- **Usuarios normales**: conviene acotar la ruta a lo que su rol IAM tiene realmente autorizado, por ejemplo `{"path": "/rds/cee-dev/api", "perfil": "min"}` → `/dev/rds/cee-dev/api`.

Si configuras una ruta más amplia que tus permisos, no pasa nada grave: ParamsX te avisará con un mensaje claro de acceso denegado en vez de una traza de boto3. Pero afinar la ruta te ahorra el error.

### Tags obligatorias y el flag `tags_activas`

En nuestra cuenta, el control de acceso a los valores privados va por **tags IAM** (condición `aws:ResourceTag/${TagKey}` sobre `GetParameter`), no por restricción de path — la única excepción es `/{entorno}/common/*`, que se concede por prefijo de ruta. Por eso estas 8 tags son ahí el mínimo no negociable: son las que sostienen todo el modelo ABAC.

```
Application, Environment, Owner, Project, Product, Service, Component, ManagedBy
```

La lista vive en `tags_obligatorias`, dentro de tu propio `paramsx_config.py`: es libre, pon las que use tu organización.

El flag `tags_activas` decide si ParamsX gestiona tags:

- **`tags_activas = True`**: al leer parámetros, el fichero exportado incluye un campo por tag con su valor actual en AWS (vacío si el parámetro es legacy y no la tiene). Al cargar, es **obligatorio** que todas tengan valor.
- **`tags_activas = False`**: las tags no aparecen en el fichero exportado en absoluto y no se valida nada (comportamiento de la 1.x).

Este flag se llamaba `abac` en la 2.0 y la 2.1. El nombre viejo se sigue aceptando, así que no tienes que tocar tu configuración, pero `tags_activas` describe lo que hace de verdad: activar la gestión de tags. Que esas tags sostengan un modelo ABAC es el motivo por el que tú las quieres, no lo que hace el flag.

Formato del fichero exportado con `tags_activas = True`:

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

En la práctica hay parámetros a los que no les aplica alguna de las 8 tags. Ese caso se controla con `obligatorias_vacias`, y solo tiene efecto si `tags_activas = True`:

| `obligatorias_vacias` | Comportamiento |
|---|---|
| `False` (por defecto) | Validación bloqueante: si a un parámetro le falta cualquiera de las tags obligatorias no se sube **ni su valor ni sus tags**. Al crear un parámetro tampoco te deja continuar dejando una tag en blanco. |
| `True` | Se permiten vacías: el parámetro se sube igualmente y **las tags sin valor no se crean en AWS** (no se suben como etiquetas vacías). En el informe de carga verás qué parámetros han quedado con tags vacías y cuáles son. |

Ojo con la diferencia entre "vacía" y "borrada": con `obligatorias_vacias = True`, una tag que se deja en blanco y **nunca existió** simplemente no se crea; pero si esa tag **ya tenía valor en AWS** y la vacías en el fichero, se interpreta como que quieres borrarla y se elimina del parámetro. Es la forma de quitar una tag.

Detalles del comportamiento con `tags_activas = True`:

- La validación es **por parámetro**, no global: con `obligatorias_vacias = False`, si a uno le falta cualquiera de las tags obligatorias no se sube ni su valor ni sus tags, y verás un error indicando qué tags faltan y a qué `parameter_name`. El resto de parámetros del fichero que estén completos se suben con normalidad.
- Cuando una carga queda a medias, los ficheros `parameters_{entorno}.py` y su backup **no se borran**, para que corrijas lo que falta y vuelvas a cargar. El backup se resincroniza con lo ya aplicado, así que la segunda pasada solo sube lo que quedó pendiente.
- Si el parámetro ya existe y le faltan tags (creado antes de esta versión), se rellenan en este mismo flujo de edición, sin borrar ni recrear el parámetro.
- Los cambios de tags se aplican con `add_tags_to_resource` / `remove_tags_from_resource` en la misma pasada que el valor. Vaciar el campo de una tag en el fichero equivale a borrarla en AWS.
- Las tags de sistema (`aws:*`) no se exportan ni se tocan. Las tags que ya existan en AWS y no estén en la lista obligatoria se conservan y se pueden editar.
- No hay forma de saltarse la validación por parámetro salvo relajarla explícitamente en tu configuración con `obligatorias_vacias = True`, o desactivar las tags por completo con `tags_activas = False`.

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
```paramsx --version```

Comandos disponibles:

| Comando | Qué hace |
|---|---|
| `paramsx` | Abre el menú interactivo (necesita configuración). |
| `paramsx configure` | Crea la configuración la primera vez; si ya existe, la revisa sin tocarla. |
| `paramsx configure --ejemplo` | Además deja la plantilla de esta versión al lado, para comparar. |
| `paramsx --version` | Versión instalada. |
| `paramsx --help` | Ayuda, con el resumen de todas las opciones de configuración. |


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
1. Selecciona la opción "Leer parámetros" en el menú. La lista muestra cada ruta con su perfil, por ejemplo `/rds  [min]` o `/API/STA  [max]`.
2. Elige el prefijo y el entorno que deseas consultar.
3. Los parámetros serán descargados y guardados en archivos como:
    - parameters_dev.py
    - parameters_dev_backup.py
    ```Importante: Los archivos se generarán en la misma ruta desde donde ejecutes el comando paramsx```
4. Edita el archivo parameters_{entorno}.py con tu software favorito. Con `tags_activas = True` cada parámetro trae además un campo por cada tag obligatoria para rellenar.

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
2. Escribe la ruta **sin el entorno**, como en tu `parameter_list`: ParamsX le aplica el perfil de `perfil_nuevos` y te enseña la ruta resultante en AWS para que la confirmes.
3. Escribe el valor: texto plano o JSON en una línea.
4. Rellena las tags obligatorias (si `tags_activas = True`). `Environment` viene precargada con el entorno elegido. Con `obligatorias_vacias = True` puedes dejar alguna en blanco pulsando Enter: esas no se crearán en AWS.
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