# Cambios

## 0.2.0 — sin publicar

La 0.1.x paginaba. Ésta corrige otras tres formas en que Oura entrega de menos
sin avisar, y abre la puerta que Oura cerró en diciembre de 2025.

Todo lo que sigue está medido contra la API real, no supuesto.

### El rango de fechas estaba mal

Pedir un solo día devolvía **cero registros** en `daily_activity`, `sleep` y
`workout`. Sin error, sin `truncado`, con `paginas: 1` afirmando que la página
venía completa. Son dos fallas que se suman:

- **`end_date` es inconsistente entre colecciones.** Tres la excluyen; siete la
  incluyen.
- **`workout` se filtra por la fecha UTC pero reporta `day` en hora local.** Con
  `-06:00`, pedir del 16 al 18 de julio devolvía los días 15 y 16.

Ahora el rango es inclusivo en los dos extremos, siempre: se piden dos días de
más de cada lado y se recortan. Es correcto sea cual sea el comportamiento de
cada colección, y lo sigue siendo cuando Oura lo cambie.

Nuevo parámetro `dia` para la consulta más común.

### Dos parámetros de Oura que no usábamos, y sus trampas

- **`campos`** → `fields`. Recorta del lado de Oura, así que baja menos.
- **`ultimo`** → `latest`. El registro más reciente sin bajar la ventana entera.

Los dos fallan en silencio si se usan mal: `fields=inventado` devuelve el
registro completo sin proyectar, y `latest=true` en una colección que no lo
soporta devuelve la colección entera. Por eso `ultimo` se rechaza aquí para las
17 que no lo respetan, y los campos que no se aplicaron se reportan en
`campos_ignorados`.

### Modo sandbox

`OURA_SANDBOX=1` usa las rutas espejo oficiales de Oura, que sirven datos
sintéticos sin pedir credenciales. Sirven 18 de las 19 colecciones —
`personal_info` no, que es la que devuelve correo, edad, peso y estatura.

### OAuth2

Oura dejó de emitir Personal Access Tokens en diciembre de 2025. `oura-mcp
--autorizar` hace el flujo completo, con `--manual` para máquinas sin navegador
y `--olvidar` para borrar las credenciales.

El refresh token de Oura es de un solo uso: se guarda antes de devolverlo, de
forma atómica, y si dos procesos refrescan a la vez el que pierde relee lo
guardado en vez de dar la sesión por perdida. El `state` del callback se
verifica con `compare_digest`.

Los tokens viven en `~/.config/oura-mcp/credenciales.json` con permisos 600 —o
en el llavero del sistema si tienes `keyring`, que no es dependencia de este
paquete. El PAT sigue funcionando y gana si está puesto.

### Volumen y avisos

- **`formato="csv"`** — 56% menos caracteres sobre un día real de `heartrate`.
  El encabezado sale de la unión de todas las claves, no del primer registro.
- **`truncado` ahora deja `continuar_desde`** para reanudar en vez de obligar a
  reintentar a ciegas.
- **429 con reintento acotado**, honrando `Retry-After` en sus dos formas. Oura
  no manda cabeceras de límite de tasa, así que reaccionar bien es lo único que
  queda.

### Errores que se leen

El `detail` de Oura llega en dos formas y ninguna se lee en crudo. Ahora se
traduce: `start_date: Input should be a valid datetime or date (recibido:
'ayer')` en vez de un JSON cortado a media palabra. Y un rango invertido se
atrapa aquí, citando las fechas que escribiste y no las que mandamos con el
margen.

### Lo demás

- Las tres herramientas declaran `title` y `readOnlyHint`. Una prueba lee el
  código fuente para que siga siendo verdad.
- El token va envuelto en `Secreto`: su `repr` no lo imprime.
- Plugin de Claude Code, `smithery.yaml`, `glama.json`, `llms.txt`.
- `herramientas/revisar_deriva.py` y un job semanal que comprueba que las 19
  colecciones sigan existiendo, sin credenciales.
- 88 pruebas, ninguna toca la red.

## 0.1.1 — 9 de agosto de 2026

Prueba de propiedad para el registro de MCP.

## 0.1.0 — 9 de agosto de 2026

Primera versión. Las 19 colecciones, tres herramientas, paginación completa.
