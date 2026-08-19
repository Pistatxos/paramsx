# ParamsX

ParamsX es una herramienta de terminal para **gestionar parámetros de AWS Systems Manager Parameter Store** de forma sencilla y controlada.

Permite descargar parámetros a un fichero editable, comparar los cambios con AWS antes de aplicarlos, crear backups y añadir nuevos parámetros sin trabajar directamente desde la consola de AWS.

Entre otras cosas, ParamsX permite:

- Leer parámetros de AWS SSM por entorno y ruta.
- Editarlos localmente.
- Comparar valores, descripciones y tags antes de aplicar cambios (y también los tipos, si desactivas `forzar_securestring`).
- Crear y eliminar parámetros.
- Gestionar tags.
- Trabajar con distintos esquemas de rutas mediante perfiles configurables.
- Crear backups parciales o completos.
- Trabajar con `SecureString` por defecto.
- Detectar errores de permisos IAM y mostrarlos de forma legible.

---

## Instalación

Instala ParamsX mediante pip:

```bash
pip install paramsx
```

Después crea la configuración inicial:

```bash
paramsx configure
```

Y ejecuta la herramienta:

```bash
paramsx
```

Para comprobar la versión instalada:

```bash
paramsx --version
```

---

## Configuración inicial

La configuración se guarda en:

**Windows**

```text
C:\Users\<tu_usuario>\.xsoft\paramsx_config.py
```

**Linux / macOS**

```text
~/.xsoft/paramsx_config.py
```

`paramsx configure` crea el fichero si todavía no existe.

Si ya tienes una configuración, **no la sobrescribe**. ParamsX comprueba las opciones disponibles y mantiene tu configuración actual.

También puedes generar una plantilla actualizada para compararla con la tuya:

```bash
paramsx configure --ejemplo
```

Esto crea:

```text
paramsx_config.ejemplo.py
```

junto a tu configuración actual.

---

## Configuración básica

Una configuración sencilla podría ser:

```python
perfiles = {
    "min": {
        "posicion_entorno": "inicio",
        "case_entorno": "lower",
        "case_ruta": "lower",
    }
}

configuraciones = {
    "profile_name": "default",
    "region_name": "eu-south-2",

    "entornos": [
        "dev",
        "pre",
        "prod",
    ],

    "parameter_list": [
        {"path": "/common", "perfil": "min"},
        {"path": "/rds", "perfil": "min"},
        {"path": "/api", "perfil": "min"},
    ],
}

perfil_nuevos = "min"

fichero_por_ruta = False
forzar_securestring = True

tags_activas = True
obligatorias_vacias = False

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

La plantilla generada con:

```bash
paramsx configure --ejemplo
```

incluye comentarios y ejemplos de todas las opciones disponibles.

---

# Cómo funciona

El flujo habitual de ParamsX es:

```text
AWS SSM
   ↓
Leer parámetros
   ↓
parameters_dev.py
   ↓
Editar localmente
   ↓
Comparar con AWS
   ↓
Revisar cambios
   ↓
Confirmar
   ↓
AWS SSM
```

Al ejecutar:

```bash
paramsx
```

se muestra un menú con las principales operaciones:

1. Leer parámetros.
2. Comparar y actualizar parámetros.
3. Crear backups.
4. Crear un nuevo parámetro.

---

## 1. Leer parámetros

Selecciona una de las rutas configuradas en `parameter_list` y el entorno que quieras consultar.

Por ejemplo:

```python
{"path": "/rds", "perfil": "min"}
```

con el entorno:

```text
dev
```

puede resolver a:

```text
/dev/rds
```

ParamsX descarga los parámetros y genera:

```text
parameters_dev.py
parameters_dev_backup.py
```

Los archivos se crean en el directorio desde el que ejecutaste `paramsx`.

Después puedes editar `parameters_dev.py` con tu editor habitual.

El backup permite conocer el estado original y calcular exactamente qué has cambiado.

---

## 2. Comparar y actualizar parámetros

Una vez hayas modificado el fichero:

```text
parameters_dev.py
```

selecciona la opción de carga.

ParamsX detecta automáticamente los ficheros disponibles en el directorio que conservan su correspondiente backup.

Antes de modificar AWS muestra una comparación con:

- **Nuevos**: parámetros que se crearán.
- **Modificados**: parámetros cuyo valor, descripción, tipo o tags han cambiado.
- **Eliminados**: parámetros que existen en AWS pero ya no aparecen en el fichero.

Nada se aplica hasta que confirmes los cambios.

Si la operación termina correctamente, los ficheros temporales se eliminan.

Si algún parámetro no puede procesarse, por ejemplo porque le faltan tags obligatorias, los ficheros se conservan para que puedas corregirlos y volver a ejecutar la carga.

---

## 3. Crear backups

ParamsX permite crear tres tipos de backup.

### Una ruta concreta

Genera un backup de una combinación determinada de ruta y entorno.

Útil para trabajar únicamente con una aplicación o servicio.

### Todas las rutas configuradas

Genera un fichero:

```text
total_listed_parameters_backup.py
```

con todos los parámetros definidos mediante `parameter_list`.

### Todos los parámetros de la cuenta

Lee Parameter Store desde:

```text
/
```

y genera:

```text
all_parameters_backup.py
```

Esta opción es útil antes de reorganizaciones o migraciones importantes.

---

## 4. Crear un parámetro nuevo

ParamsX también permite crear parámetros sin salir de la herramienta.

Selecciona:

```text
Crear nuevo parámetro
```

y elige el entorno.

Después introduce la ruta **sin el entorno**, igual que la declararías en `parameter_list`.

Por ejemplo:

```text
/rds/cee-dev/api/alertas
```

Si el perfil utiliza el entorno al inicio y seleccionas `dev`, ParamsX construirá:

```text
/dev/rds/cee-dev/api/alertas
```

Antes de continuar verás siempre la ruta final que se creará en AWS.

Después podrás introducir:

- descripción;
- valor;
- tags obligatorias, si están activadas.

El valor puede ser texto plano o JSON en una línea:

```json
{"host": "db.example.com", "user": "api", "pass": "secret"}
```

Antes de crear el parámetro se muestra una pantalla de confirmación.

Los parámetros nuevos se crean con:

```text
Overwrite=False
```

por lo que ParamsX nunca sobrescribe accidentalmente un parámetro existente mediante esta opción.

---

# Perfiles

No todas las organizaciones utilizan la misma estructura para sus parámetros.

Por eso ParamsX **no impone una convención de rutas**.

Cada entrada de `parameter_list` utiliza un perfil que define cómo construir la ruta real de AWS.

Un perfil tiene tres propiedades:

| Campo | Valores |
|---|---|
| `posicion_entorno` | `inicio`, `final`, `mixto`, `ninguno` |
| `case_entorno` | `lower`, `upper`, `capitalize` |
| `case_ruta` | `lower`, `upper`, `capitalize`, `ninguno` |

Por ejemplo:

```python
perfiles = {
    "min": {
        "posicion_entorno": "inicio",
        "case_entorno": "lower",
        "case_ruta": "lower",
    },

    "max": {
        "posicion_entorno": "final",
        "case_entorno": "upper",
        "case_ruta": "ninguno",
    },

    "mixto_max": {
        "posicion_entorno": "mixto",
        "case_entorno": "upper",
        "case_ruta": "ninguno",
    },
}
```

Los nombres de los perfiles los eliges tú: define solo los que utilice tu organización.

---

## Posición del entorno

### `inicio`

```text
Ruta declarada: /rds
Entorno: dev
Perfil: min

→ /dev/rds
```

### `final`

```text
Ruta declarada: /API/STA
Entorno: dev
Perfil: max

→ /API/STA/DEV
```

### `mixto`

Permite indicar exactamente dónde debe insertarse el entorno mediante `*`.

```text
Ruta declarada: /API/MULTIAPI/*/stan_ai
Entorno: dev
Perfil: mixto_max

→ /API/MULTIAPI/DEV/stan_ai
```

El `*`:

- debe ocupar un segmento completo;
- debe aparecer exactamente una vez;
- solo puede utilizarse con perfiles `mixto`.

Además de colocar el entorno, permite acotar la lectura a un subárbol concreto.

### `ninguno`

No añade ningún entorno a la ruta.

Por ejemplo:

```text
/api/sta/auth
```

se utiliza tal cual.

Esto puede resultar útil cuando cada entorno utiliza una cuenta AWS diferente.

---

## Case del entorno

`case_entorno` decide cómo se escribe el entorno.

Para el entorno canónico:

```text
dev
```

los posibles resultados son:

```text
lower       → dev
upper       → DEV
capitalize  → Dev
```

La lista definida en:

```python
configuraciones["entornos"]
```

es siempre la lista canónica.

Por ejemplo:

```python
"entornos": ["dev", "pre", "prod"]
```

Si tu organización utiliza `staging` en vez de `pre`, simplemente debes configurarlo ahí.

---

## Case de la ruta

`case_ruta` solo se utiliza **al crear parámetros nuevos**.

Por ejemplo, si escribes:

```text
/API/MULTIAPI/Token
```

el resultado puede ser:

```text
lower       → /api/multiapi/token
upper       → /API/MULTIAPI/TOKEN
capitalize  → /Api/Multiapi/Token
ninguno     → /API/MULTIAPI/Token
```

ParamsX **no renombra ni modifica el case de parámetros que ya existen en AWS**.

Los parámetros existentes siempre se leen y editan respetando exactamente su ruta actual.

---

# `parameter_list`

`parameter_list` define las rutas con las que quieres trabajar.

Por ejemplo:

```python
"parameter_list": [
    {"path": "/common", "perfil": "min"},
    {"path": "/rds", "perfil": "min"},
    {"path": "/EMAIL", "perfil": "max"},
    {"path": "/API/STA", "perfil": "max"},
    {"path": "/API/MULTIAPI/*/stan_ai", "perfil": "mixto_max"},
]
```

Cada entrada contiene:

```python
{
    "path": "...",
    "perfil": "..."
}
```

El perfil determina cómo transformar esa ruta en la ruta real de AWS, y tiene que estar definido en `perfiles`.

---

## Acotar las rutas

`parameter_list` es únicamente tu **vista de trabajo**.

La seguridad real siempre la controla **IAM**.

Un administrador podría trabajar con:

```python
{"path": "/rds", "perfil": "min"}
```

que resolvería a:

```text
/dev/rds
```

Mientras que un usuario con permisos más limitados podría utilizar:

```python
{"path": "/rds/cee-dev/api", "perfil": "min"}
```

que resolvería a:

```text
/dev/rds/cee-dev/api
```

Si intentas leer una ruta para la que no tienes permisos, ParamsX muestra un error legible en lugar de una traza completa de boto3.

Por ejemplo:

```text
⚠ No tienes permisos para leer: /dev/rds

Pídele a un administrador que te dé acceso o configura
una ruta más específica en parameter_list.
```

---

# Un fichero por ruta

Por defecto, ParamsX utiliza nombres como:

```text
parameters_dev.py
parameters_dev_backup.py
```

Esto significa que si lees dos rutas distintas del mismo entorno, la segunda lectura podría reemplazar el fichero de la primera.

ParamsX pide confirmación antes de hacerlo.

Si trabajas habitualmente con varias rutas del mismo entorno puedes activar:

```python
fichero_por_ruta = True
```

En ese caso cada combinación de ruta y perfil genera su propio fichero.

Por ejemplo:

| Configuración | Fichero |
|---|---|
| `/API/STA` + `max` | `parameters_dev__API_STA__max.py` |
| `/API/*/STA` + `mixto_max` | `parameters_dev__API_env_STA__mixto_max.py` |

---

# Descripción de los parámetros

ParamsX también puede leer y modificar la descripción de un parámetro.

El fichero exportado puede contener:

```python
parametros = [
    {'parameter_name': '/dev/api/sta/token',
     'parameter_description': "Token JWT de la API, rota cada 90 dias",
     'parameter_value': """abc123"""},
]
```

Para leer las descripciones es necesario que el rol tenga:

```text
ssm:DescribeParameters
```

La descripción no viaja junto al valor: es un metadato y se pide con una llamada aparte.

Si el rol no dispone de este permiso:

- ParamsX muestra un aviso.
- `parameter_description` no aparece en el fichero.
- La descripción existente en AWS no se modifica.

Un cambio de descripción aparece en la comparación como:

```text
Modificado (descripción)
```

o, si también cambia el valor:

```text
Modificado (valor | descripción)
```

---

# SecureString

Por defecto:

```python
forzar_securestring = True
```

ParamsX guarda los parámetros como:

```text
SecureString
```

Esto evita depender de que cada usuario recuerde seleccionar manualmente el tipo cifrado.

| Valor | Comportamiento |
|---|---|
| `True` | Todo lo que se sube se guarda como `SecureString`. |
| `False` | Los parámetros existentes conservan su tipo (`String`, `StringList` o `SecureString`). |

Con `False` nada se descifra: lo que ya era `SecureString` lo sigue siendo. Lo único que cambia es que ParamsX deja de convertir los que no lo son.

Con:

```python
forzar_securestring = False
```

el fichero exportado también incluye:

```python
parameter_type
```

para permitir modificar explícitamente el tipo.

Los parámetros creados desde la opción **Crear nuevo parámetro** se crean siempre como `SecureString`.

---

# Tags

La gestión de tags se controla mediante:

```python
tags_activas = True
```

Con las tags activadas:

- se leen las tags actuales desde AWS;
- aparecen en el fichero exportado;
- se pueden modificar;
- se validan antes de aplicar cambios.

Por ejemplo:

```python
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

El fichero exportado puede contener:

```python
parametros = [
    {'parameter_name': '/dev/email/users',
     'parameter_description': "Buzon que recibe los avisos de altas",
     'parameter_value': """usuario@example.com""",
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

La lista de tags es completamente configurable.

ParamsX no obliga a utilizar estas ocho.

---

## Tags obligatorias vacías

El comportamiento se controla mediante:

```python
obligatorias_vacias = False
```

### `False`

Es el comportamiento por defecto.

Si falta una tag obligatoria:

- ese parámetro no se sube;
- tampoco se modifican su valor ni sus tags;
- ParamsX muestra qué tags faltan.

El resto de parámetros válidos del fichero sí pueden procesarse.

### `True`

Permite dejar tags vacías.

Las tags vacías **no se crean en AWS**.

Hay una diferencia importante entre una tag vacía y eliminar una existente:

- Si la tag nunca existió y está vacía, simplemente no se crea.
- Si la tag ya existía en AWS y vacías su valor en el fichero, ParamsX interpreta que quieres eliminarla.

Las tags del sistema:

```text
aws:*
```

no se exportan ni se modifican.

---

# IAM y seguridad

ParamsX no sustituye la seguridad de AWS.

Los permisos reales siempre los determina IAM.

`parameter_list` únicamente indica qué rutas intentará consultar ParamsX.

Por ejemplo, una organización puede permitir lectura general sobre:

```text
/{entorno}/common/*
```

y controlar parámetros privados mediante tags IAM y políticas ABAC.

La estructura exacta depende de la organización.

---

# Ejemplo de convención de rutas

ParamsX no obliga a utilizar ninguna convención concreta, pero una estructura posible es:

```text
/{entorno}/{servicio}/{nombre-servicio}/{servicio-adjunto}/{definición}
```

Por ejemplo:

```text
/dev/api/multiapi/bbdd
/dev/email/users
/dev/common/email/users
/dev/common/rds/cee-dev
/dev/rds/cee-dev/api/alertas-premium
/dev/api/alertas-premium/encryption_key
/dev/api/sta/auth/jwt_secret
```

En esta estructura:

- `{entorno}` identifica `dev`, `pre`, `prod`, etc.
- `{servicio}` identifica la categoría o servicio.
- `{definición}` describe el dato almacenado.

Esta es solo una posible convención. Los perfiles permiten adaptar ParamsX a otros esquemas existentes.

---

## Correlación de parámetros RDS

Si utilizas una estructura donde los datos públicos y privados de una conexión RDS están separados, el nombre del servicio debe coincidir.

Por ejemplo:

```text
/dev/common/rds/cee-dev
```

puede contener:

```text
host
port
database
```

mientras:

```text
/dev/rds/cee-dev/api/alertas
```

puede contener:

```text
user
password
```

`cee-dev` permite correlacionar ambas partes.

Al crear un parámetro mediante la opción 4, ParamsX puede comprobar que exista la contraparte correspondiente.

Si no existe, muestra un aviso.

El aviso no bloquea la creación.

---

# Configuración del PATH

En algunos entornos el comando `paramsx` puede no quedar disponible automáticamente después de instalar el paquete.

## Windows

Añade al `PATH` de usuario:

```text
C:\Users\<tu_usuario>\AppData\Roaming\Python\Python<version>\Scripts
```

Por ejemplo, para Python 3.12:

```text
C:\Users\<tu_usuario>\AppData\Roaming\Python\Python312\Scripts
```

Después abre una terminal nueva.

## Linux / macOS

Añade a tu configuración de shell:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Para bash:

```bash
source ~/.bashrc
```

Para zsh:

```bash
source ~/.zshrc
```

Comprueba finalmente:

```bash
paramsx --version
```

---

# Comandos disponibles

| Comando | Descripción |
|---|---|
| `paramsx` | Abre el menú interactivo. |
| `paramsx configure` | Crea o comprueba la configuración. |
| `paramsx configure --ejemplo` | Genera la plantilla completa de configuración. |
| `paramsx --version` | Muestra la versión instalada. |
| `paramsx --help` | Muestra la ayuda disponible. |

---

# Migración desde ParamsX 1.x

> ⚠️ **Breaking change desde ParamsX 2.0**

Desde ParamsX 2.0, `parameter_list` ya no es una lista de strings.

Antes:

```python
"parameter_list": [
    "/rds",
    "/api",
]
```

Ahora cada ruta indica también el perfil que utiliza:

```python
"parameter_list": [
    {"path": "/rds", "perfil": "min"},
    {"path": "/api", "perfil": "min"},
]
```

Si ParamsX detecta una configuración antigua, no intenta interpretarla de forma ambigua y muestra cómo actualizarla.

## Nombres antiguos que se siguen aceptando

Algunas opciones se han renombrado para que digan lo que hacen. **Los nombres antiguos siguen funcionando**, así que actualizar no obliga a tocar la configuración:

| Nombre antiguo | Nombre actual |
|---|---|
| `abac` | `tags_activas` |
| `naming` | `perfiles` |
| `convencion` (en `parameter_list`) | `perfil` |
| `convencion_nuevos` | `perfil_nuevos` |

`paramsx configure` indica qué nombres antiguos utiliza tu configuración y cómo se llaman ahora.

Consulta el `CHANGELOG.md` para conocer los cambios específicos de cada versión.

---

# Operaciones masivas

Antes de realizar una reorganización importante de Parameter Store es recomendable crear un backup completo.

Desde la opción de backups puedes generar:

```text
all_parameters_backup.py
```

con todos los parámetros accesibles de la cuenta.

Ese fichero puede utilizarse como respaldo antes de realizar cambios masivos o migraciones.

Revisa siempre cuidadosamente la comparación antes de confirmar eliminaciones o modificaciones.

---

# Licencia

ParamsX se distribuye bajo licencia MIT.

Puedes utilizarlo, modificarlo y adaptarlo a tus necesidades.

ParamsX modifica recursos reales de AWS. Revisa siempre los cambios mostrados en la pantalla de confirmación antes de aplicarlos.
