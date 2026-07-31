# Changelog

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
  - `max` (convención legacy): el entorno en mayúscula se inserta **tras el primer segmento**. `/API/STA` + `dev` → `/API/DEV/STA`; `/EMAIL` + `dev` → `/EMAIL/DEV`.
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
