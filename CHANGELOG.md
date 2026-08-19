# Changelog

## 2.3.0

### Añadido

- **La descripción de los parámetros, editable como el valor.** El fichero exportado trae un campo `parameter_description` **debajo del nombre y antes del valor**: se lee de AWS, lo editas y al cargar se actualiza. Los cambios de descripción se detectan igual que los de valor y aparecen en la pantalla de confirmación como `Modificado (descripción)`. La opción 4 también la pide al crear un parámetro, entre la ruta y el valor.
- Los backups incluyen la descripción, así que un backup restaura también las descripciones.
- **Flag `forzar_securestring`** (por defecto `True`, el comportamiento de siempre): todo lo que sube ParamsX va cifrado como `SecureString`. Con `False` se respeta el tipo que ya tuviera el parámetro en AWS: al actualizar no se manda el tipo y AWS conserva el suyo (`Type` solo es obligatorio al crear). El fichero exportado trae además un campo `parameter_type` editable, por si quieres cambiar el tipo a propósito, y sus cambios se detectan como los del valor o la descripción. El tipo se lee de la misma llamada que el valor, así que no hace falta ningún permiso nuevo.

### Nota sobre el valor y la descripción

`put_parameter` con `Overwrite=True` reescribe la definición del parámetro, así que ParamsX **manda siempre la descripción que trae el fichero**, incluso cuando lo único que cambió fue el valor. Antes no se mandaba, y una descripción que ya existiera en AWS podía quedarse vacía al editar el valor.

### Nota sobre permisos

Leer las descripciones necesita **`ssm:DescribeParameters`**, porque no vienen en `GetParametersByPath` (son metadatos, no valores). Si tu rol no lo tiene, ParamsX te avisa al leer, el campo no aparece en el fichero y al cargar **no se toca** la descripción que haya en AWS. El resto sigue funcionando igual.

## 2.2.2

Un renombrado de la configuración, sin cambios de comportamiento. **Los nombres antiguos
se siguen aceptando**, así que no tienes que tocar tu fichero para actualizar.

### Cambiado

- **Un solo nombre para el concepto: `perfiles` / `perfil`.** El mismo concepto se llamaba de tres formas distintas: el diccionario era `naming`, la clave de cada entrada de `parameter_list` era `convencion` y la documentación decía "perfil". Explicárselo a alguien obligaba a traducir dos veces. Ahora:

  | Antes | Ahora |
  |---|---|
  | `naming = {...}` | `perfiles = {...}` |
  | `{"path": "/rds", "convencion": "min"}` | `{"path": "/rds", "perfil": "min"}` |
  | `convencion_nuevos = "min"` | `perfil_nuevos = "min"` |

- `paramsx configure` te dice qué nombres antiguos usas y cómo se llaman ahora, incluidas las entradas de `parameter_list`. Los viejos (`naming`, `convencion`, `convencion_nuevos` y el `abac` de la 2.0) se traducen al cargar, así que dentro del programa solo existe el nombre nuevo.

## 2.2.1

Solo comandos de terminal y documentación: no cambia nada de la lectura, la carga ni la
construcción de rutas. Si ya tienes la 2.2.0 funcionando, actualizar no te obliga a tocar
tu configuración.

### Añadido

- **`paramsx --version`** (y `-v`), y la versión también en la cabecera de `paramsx --help`. La versión pasa a vivir en `paramsx/__init__.py` y `setup.py` la lee de ahí, para que el paquete y el comando no puedan decir cosas distintas.
- **`paramsx configure` sobre una configuración que ya existe ya no se queda en "no se sobrescribirá".** Sigue sin tocar el fichero, pero ahora te dice qué opciones nuevas no tienes y con qué valor por defecto se rellenan, si usas el nombre antiguo `abac`, y si la configuración es válida.
- **`paramsx configure --ejemplo`**: además de lo anterior, deja la plantilla de esta versión en `~/.xsoft/paramsx_config.ejemplo.py`, al lado de la tuya, para comparar. ParamsX no la lee: es solo referencia. Escribir en tu configuración es lo único que no se puede deshacer, así que va en un comando aparte y en otro fichero.
- Mensaje de primer arranque más claro cuando todavía no hay configuración, explicando qué hace `paramsx configure` y dónde va el fichero.

### Cambiado

- **`paramsx --help` al día.** La opción 2 ya explica que eliges entre los ficheros que tengas en el directorio; el ejemplo de `mixto` usa el entorno en mayúscula como el resto de la documentación; `fichero_por_ruta` enseña el nombre real (`parameters_dev__API_STA__max.py`); y se documentan `profile_name`, `region_name` y `entornos`, que no aparecían aunque son obligatorios.
- **El README muestra el contenido literal de `paramsx_config.py`**, con sus comentarios y tablas, en vez de una versión resumida: es exactamente lo que te crea `paramsx configure`, así que no pueden desincronizarse. Y una tabla con todos los comandos disponibles.

## 2.2.0

### Añadido

- **Perfiles de naming libres.** `min` y `max` dejan de estar cableados en el código: ahora son entradas de un diccionario `naming` en `~/.xsoft/paramsx_config.py` que puedes redefinir, ampliar y renombrar. Cada perfil declara tres cosas:
  - `posicion_entorno`: `inicio` (`/rds` → `/dev/rds`), `final` (`/API/STA` → `/API/STA/DEV`), `mixto` (`/API/*/STA` → `/API/dev/STA`) o `ninguno` (`/api/sta/auth` → `/api/sta/auth`).
  - `case_entorno`: `lower`, `upper` o `capitalize`.
  - `case_ruta`: `lower`, `upper`, `capitalize` o `ninguno`; a qué case se fuerza la ruta al crear un parámetro nuevo. Con `ninguno` se respeta lo que escribas.
- **Marcador `*` para colocar el entorno donde quieras** (perfiles `mixto`). Sirve para acotar la lectura a un subárbol concreto: `/API/MULTIAPI/*/stan_ai` lee solo `/API/MULTIAPI/DEV/stan_ai` en vez de todo lo que cuelga de `/API/MULTIAPI/DEV`. El `*` debe ser un segmento entero y aparecer exactamente una vez.
- **`posicion_entorno: "ninguno"`**, para cuentas que separan los entornos por cuenta de AWS y no meten el entorno en la ruta. Antes esas cuentas no podían usar ParamsX: toda ruta recibía un segmento de entorno sí o sí.
- **`fichero_por_ruta`**: con `True`, el fichero exportado incluye la ruta y el perfil en su nombre (`parameters_dev__API_STA__max.py`), así leer una segunda ruta del mismo entorno no machaca la que estabas editando. Con `False` (por defecto) se mantiene el nombre de siempre. En los dos modos ParamsX **pide confirmación antes de sobrescribir** un fichero de una lectura anterior, porque volver a leer la misma ruta también se lleva por delante lo que tuvieras editado.
- **La carga (opción 2) lista los ficheros que hay en el directorio**, en vez de pedir ruta y entorno y fallar si no existe el fichero correspondiente. Se ofrecen los que conservan su backup al lado, se lean con `fichero_por_ruta` o sin él, e incluso los de una ruta que ya hayas quitado de tu `parameter_list`.
- **`convencion_nuevos`**: qué perfil usan los parámetros creados con la opción 4. Si no lo declaras, se usa el primer perfil de `naming`.
- **Validación de la configuración al arrancar**, para que un naming mal declarado se vea como un error y no como una lista de parámetros vacía: perfil inexistente, `posicion_entorno`/`case_entorno`/`case_ruta` con valores inválidos, perfil `mixto` sin `*`, `*` en un perfil que no es `mixto`, más de un `*`, `*` pegado a un segmento, y aviso si dos entradas resuelven a la misma ruta.

### Cambiado

- **`abac` pasa a llamarse `tags_activas`.** Es el mismo interruptor de siempre (gestionar y validar tags), con un nombre que dice lo que hace en vez de por qué lo queremos nosotros. **El nombre viejo se sigue aceptando**, así que las configuraciones de la 2.0 y la 2.1 funcionan sin tocar nada.
- **La opción 4 (crear parámetro) ya no está cableada a `min`.** Antes forzaba toda la ruta a minúscula y exigía que el primer segmento fuera el entorno, así que quien nombra sus parámetros en mayúscula no podía crearlos con la herramienta. Ahora se escribe la ruta **sin el entorno**, igual que en `parameter_list`, y ParamsX aplica el perfil de `convencion_nuevos`, respeta el case según `case_ruta` y enseña la ruta resultante en AWS para confirmarla antes de seguir.

### Corregido

- **La convención `max` ponía el entorno en el medio de la ruta.** Con rutas de más de un segmento el entorno se insertaba tras el primer segmento (`/API/MULTIAPI` + `dev` → `/API/DEV/MULTIAPI`), cuando en `max` el entorno va **siempre al final**: `/API/MULTIAPI` + `dev` → `/API/MULTIAPI/DEV`. Con esa inserción en medio, ninguna ruta `max` de más de un segmento resolvía a una ruta real, así que no se veían los parámetros. Las rutas de un solo segmento (`/EMAIL` → `/EMAIL/DEV`) no cambian: ahí el resultado ya era correcto.
- La documentación de la 2.0.0 (README, plantilla de configuración y `paramsx --help`) describía esa inserción en medio como el comportamiento esperado de `max`, con el ejemplo `/API/STA` → `/API/DEV/STA`. Corregida: el ejemplo correcto es `/API/STA` → `/API/STA/DEV`.

### Actualizar desde la 2.1.0

No hay que tocar nada: sin `naming` en tu fichero se usan los perfiles de la plantilla, donde `min` y `max` significan lo mismo que antes, y `abac` se sigue leyendo como `tags_activas`. Todo lo nuevo (`*`, `ninguno`, `fichero_por_ruta`, `convencion_nuevos`) es opcional. Si quieres usarlo, la forma más rápida de ver la plantilla nueva entera es `paramsx --help` o el README.

## 2.1.0

### Añadido

- **Flag `obligatorias_vacias`** en `~/.xsoft/paramsx_config.py`. Solo tiene efecto con `abac = True`:
  - `False` (valor por defecto, comportamiento de la 2.0.0): validación bloqueante. Si a un parámetro le falta cualquiera de las tags obligatorias no se sube ni su valor ni sus tags, y al crear un parámetro no se puede dejar una tag en blanco.
  - `True`: se permite dejar vacías las tags obligatorias. El parámetro se sube igualmente y **las tags sin valor no se crean en AWS**: nunca se suben etiquetas vacías. En la creación puedes saltar una tag pulsando Enter y el resumen previo lista cuáles quedan vacías.
- El informe de carga incluye un bloque `Tags obligatorias vacías` con el parámetro y las tags afectadas, para dejar constancia sin bloquear.

No hay que tocar nada en la configuración para actualizar desde la 2.0.0: si no defines `obligatorias_vacias`, se asume `False` y todo sigue igual.

### Nota

Vaciar una tag **que ya tenía valor en AWS** sigue significando borrarla del parámetro, en los dos modos. Es la forma de eliminar una tag. Lo que cambia con `obligatorias_vacias = True` es que una tag en blanco que nunca existió simplemente no se crea, en vez de bloquear la subida.

## 2.0.0

### ⚠ Breaking change: hay que actualizar `~/.xsoft/paramsx_config.py` a mano

`parameter_list` **ya no es una lista de strings**: cada entrada es ahora un diccionario que declara su convención de naming. El formato antiguo no es compatible y ParamsX se niega a arrancar mostrando cómo migrarlo.

Antes (1.x):

```python
    "entornos": ["DEV", "PROD"],
    "parameter_list": [
        "/params1/xx",
        "/params2/xx",
    ]
```

Ahora (2.0.0):

```python
    "entornos": ['dev', 'pre', 'prod'],   # SIEMPRE en minúscula, lista canónica única
    "parameter_list": [
        {"path": "/common", "convencion": "min"},
        {"path": "/rds", "convencion": "min"},
        {"path": "/EMAIL", "convencion": "max"},
        {"path": "/API/STA", "convencion": "max"},
    ]
```

Además:
- `entornos` se escribe **siempre en minúscula**. El entorno en mayúscula de las rutas `max` se deriva con `.upper()` de esa misma lista.
- Ya **no existe** `entornos_old`.
- Los ficheros temporales pasan a llamarse `parameters_dev.py` (antes `parameters_DEV.py`) al usar entornos en minúscula.

### Añadido

- **Doble convención de naming en `parameter_list`.** Cada ruta declara `"convencion": "min"` o `"max"`:
  - `min` (convención nueva): el entorno en minúscula se añade **al principio**. `/rds` + `dev` → `/dev/rds`.
  - `max` (convención legacy): el entorno en mayúscula se inserta **tras el primer segmento**. `/API/STA` + `dev` → `/API/DEV/STA`; `/EMAIL` + `dev` → `/EMAIL/DEV`. (Esto era un bug, corregido en la 2.2.0: el entorno va al final, `/API/STA/DEV`.)
- **Opción 4 del menú: "Crear nuevo parámetro".** Pide ruta (siempre en convención `min`, forzada a minúscula), valor (texto plano o JSON, validado) y las tags obligatorias. Se crea con `Overwrite=False` para no machacar nada. No se puede crear un parámetro con la convención `max`.
- **Aviso de correlación de naming en RDS.** Al crear un parámetro de RDS se comprueba que exista su contraparte (`/{entorno}/common/rds/{nombre-servicio}` ↔ `/{entorno}/rds/{nombre-servicio}/...`) y se avisa si falta. Es un aviso, no bloquea.
- **Flag `abac` y tags obligatorias.** Con `abac = True`, el fichero exportado incluye un campo por tag (`tagApplication`, `tagEnvironment`, `tagOwner`, `tagProject`, `tagProduct`, `tagService`, `tagComponent`, `tagManagedBy`) con su valor actual en AWS. Estas 8 tags sostienen el control de acceso ABAC vía IAM de toda la cuenta. La lista vive en `tags_obligatorias`, en el propio fichero de configuración, para poder ampliarla sin tocar código. Con `abac = False` no aparecen tags en el fichero y no se valida nada (comportamiento 1.x).
- **Validación bloqueante por parámetro.** Al cargar con `abac = True`, si a un parámetro le falta cualquiera de las tags obligatorias no se sube ni su valor ni sus tags, y se indica qué falta y en qué `parameter_name`. El resto del lote se sube con normalidad. Cuando la carga queda a medias los ficheros no se borran y el backup se resincroniza con lo ya aplicado, así que la segunda pasada solo sube lo pendiente.
- **Round-trip de tags en la edición.** Los diffs de tags se detectan igual que los de valores (Nuevos / Modificados / Eliminados) y se aplican con `add_tags_to_resource` / `remove_tags_from_resource` en la misma pasada que el valor, sin borrar ni recrear el parámetro. Vaciar el campo de una tag la borra en AWS. Los backups automáticos incluyen las tags.

### Cambiado

- **Errores de permisos legibles.** `AccessDeniedException` se captura de forma específica y se muestra como `⚠ No tienes permisos para leer: /dev/rds — pídele a un admin que te dé acceso, o acota la ruta en tu parameter_list...`, sin traza de boto3. Cualquier otro error de AWS (ruta inexistente, throttling...) se propaga con su traza normal en lugar de quedar oculto tras un `except Exception`.
- Los cambios que solo afectan a tags ya no generan una versión nueva del valor del parámetro.
- Las pantallas de resultado son informes con scroll en vez de un mensaje centrado de 3 segundos.
- Las tags de sistema (`aws:*`) no se exportan ni se modifican. Las tags existentes que no estén en la lista obligatoria se conservan.
- `paramsx configure` copia la plantilla que trae el paquete, así que el fichero generado y la documentación no se pueden desincronizar.
- La configuración se valida antes de entrar en la interfaz curses, con los errores impresos en la terminal.
- `paramsx --help` documenta las opciones del menú y las claves de configuración.

### Corregido

- El menú de backup ya no muta `parameter_list` para añadir y quitar sus dos opciones extra.
- El backup "Total parámetros listados" ya no se interrumpe cuando una ruta no tiene parámetros en algún entorno o no es accesible: continúa con el resto y avisa al final.
- Los mensajes largos ya no rompen la pantalla: se ajustan al ancho del terminal.
