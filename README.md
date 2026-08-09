# oura-mcp

La API v2 de [Oura](https://ouraring.com) como servidor [MCP](https://modelcontextprotocol.io).
Las 19 colecciones, tres herramientas, cero dependencias fuera del SDK de MCP.

**Lo que lo distingue: Oura entrega de menos sin avisar, de cuatro maneras
distintas, y este servidor las corrige todas.** Suena a poco y es todo el punto
— ver abajo.

---

## El problema, medido

Oura no devuelve errores cuando le pides algo que no puede darte. Devuelve algo
distinto, con forma de respuesta correcta. Las cuatro que encontramos midiendo
contra la API real, el 9 de agosto de 2026:

### 1. Si no sigues la paginación, recibes una fracción

```json
{ "data": [ ... ], "next_token": "eyJ0eXAiOi..." }
```

Si `next_token` viene y no lo persigues, recibes la primera página y **nada te
avisa**. Un día de `heartrate` —una persona, un anillo, 24 horas— son **1,231
muestras repartidas en 2 páginas**. Quien no pagina recibe 1,000 de 1,231: el
81%, con aspecto de estar completo. Un mes son ~37,000.

### 2. Pedir un solo día devolvía cero registros

`end_date` **no se comporta igual en todas las colecciones**:

| Excluyen el último día pedido | Lo incluyen |
|---|---|
| `daily_activity`, `sleep`, `workout` | `daily_sleep`, `daily_readiness`, `daily_stress`, `daily_spo2`, `daily_resilience`, `daily_cardiovascular_age`, `sleep_time` |

Y encima **`workout` se filtra por la fecha UTC pero reporta `day` en hora
local**: con `-06:00`, pedir del 16 al 18 de julio devolvía registros de los
días 15 y 16 — anteriores al inicio pedido.

Aquí el rango es inclusivo en los dos extremos, siempre. Se piden dos días de
más de cada lado y se recortan, lo que es correcto sea cual sea el
comportamiento de cada colección — y lo sigue siendo cuando Oura lo cambie.

### 3. `latest=true` lo ignora donde no aplica

Sólo lo respetan `heartrate` y `ring_battery_level`. En las otras diecisiete
Oura no da error: **devuelve la colección entera**. Pides el último registro,
recibes diez, y crees que es uno. Aquí se rechaza antes de salir a la red.

### 4. Un campo que no existe se ignora en silencio

`fields=no_existe` devuelve el registro **completo** —la proyección no ocurre— y
`fields=score,no_existe` aplica el bueno y tira el malo sin decir nada. Aquí, los
campos que no aparecieron se reportan en `campos_ignorados`.

**El patrón es siempre el mismo:** pides una cosa, recibes otra, nada te avisa.
Por eso este paquete prefiere gritar antes que entregar de menos en silencio.

## Instalación

### Pruébalo sin credenciales

```bash
pip install mcp-oura
OURA_SANDBOX=1 oura-mcp --revisar
```

El sandbox es oficial —está en el OpenAPI de Oura, con 34 rutas espejo— y sirve
datos sintéticos sin pedir autenticación. Sirven 18 de las 19 colecciones:
`personal_info` no, y tiene sentido, es la que devuelve correo, edad, peso y
estatura.

Es el orden correcto: primero ves el servidor andar y entiendes la forma de los
datos; después consigues credenciales.

### Con tus propios datos

**Oura dejó de emitir Personal Access Tokens en diciembre de 2025.** Los que ya
existían siguen funcionando; nuevos no se pueden crear. Así que hay dos caminos:

**a) OAuth2 — el que funciona hoy.** Registra una aplicación en
[cloud.ouraring.com/oauth/applications](https://cloud.ouraring.com/oauth/applications)
con el redirect `http://localhost:9876/callback/` — **la diagonal final es
obligatoria**, el portal rechaza la otra forma con `invalid_redirect_uri`.

```bash
export OURA_CLIENT_ID="…"
export OURA_CLIENT_SECRET="…"
oura-mcp --autorizar             # abre el navegador y espera el callback
oura-mcp --autorizar --manual    # máquinas sin navegador: pegas la URL de vuelta
```

El token se guarda en `~/.config/oura-mcp/credenciales.json` con permisos 600
—o en el llavero del sistema si tienes `keyring` instalado, que no es una
dependencia de este paquete— y se renueva solo. `oura-mcp --olvidar` lo borra.

**b) Un token personal, si ya tenías uno.**

```bash
export OURA_PAT="tu-token"
oura-mcp --revisar
```

`--revisar` es el autodiagnóstico: dice con qué te estás autenticando, qué
alcances te concedieron y cuánto le queda al acceso, **sin devolver el token ni
un solo dato de salud**. Reporta la longitud del token, nunca el token. Los
mensajes de error se copian y se pegan en chats y en issues; no tienen por qué
arrastrar nada más.

### Conectarlo a Claude Code

Con el paquete ya instalado (`pip install mcp-oura`):

```bash
claude mcp add -s user oura --env OURA_SANDBOX=1 -- oura-mcp
```

Quita `OURA_SANDBOX` cuando hayas corrido `oura-mcp --autorizar`.

**Si usas [uv](https://docs.astral.sh/uv/)**, no hace falta instalar nada de
forma permanente:

```bash
claude mcp add -s user oura --env OURA_SANDBOX=1 -- uvx --from mcp-oura oura-mcp
```

El `--from` es necesario porque la distribución se llama `mcp-oura` y el
ejecutable `oura-mcp`. *(Esto requiere tener `uv`; si no lo tienes, el comando de
arriba falla con «command not found» y la ruta buena es `pip install`.)*

Si usas un token personal, mejor en un archivo aparte que en la configuración:

```bash
printf '%s' "tu-token" > ~/.oura_pat && chmod 600 ~/.oura_pat
claude mcp add -s user oura --env OURA_PAT_FILE=$HOME/.oura_pat -- uvx --from mcp-oura oura-mcp
```

Un servidor MCP se registra en un JSON que se respalda, se sincroniza y se
comparte al pedir ayuda. Un token ahí queda en claro; en un archivo con permisos
600 se rota sin tocar la configuración.

### Conectarlo a Claude Desktop

En `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "oura": {
      "command": "/ruta/completa/a/oura-mcp",
      "env": { "OURA_SANDBOX": "1" }
    }
  }
}
```

La ruta completa la da `which oura-mcp`. Claude Desktop no hereda el `PATH` de
tu terminal, así que un nombre pelado ahí falla en silencio — es de los errores
más comunes al configurar un servidor MCP. Quita `OURA_SANDBOX` cuando hayas
corrido `oura-mcp --autorizar`.

## Las herramientas

| | |
|---|---|
| `oura_colecciones` | Las 19, con qué trae cada una y qué parámetros pide |
| `oura_consultar` | Trae una colección completa en un rango, paginando hasta el final |
| `oura_revisar` | Autodiagnóstico sin exponer nada |

**Tres, no diecinueve.** Un servidor con una herramienta por colección obliga al
modelo a elegir entre 19 nombres parecidos antes de saber qué contienen. Aquí la
colección es un parámetro y el catálogo se consulta cuando hace falta.

Las tres se declaran de sólo lectura, y no es una promesa: no hay un `POST`, un
`PUT` ni un `DELETE` en todo el paquete, y una prueba lee el código fuente para
que siga siendo cierto.

### Parámetros de `oura_consultar`

| | |
|---|---|
| `dia` | Un solo día. Atajo de `inicio=fin=dia` |
| `inicio`, `fin` | El rango, **inclusivo en los dos extremos** |
| `campos` | Sólo estos. Oura recorta del lado suyo, así que baja menos |
| `ultimo` | El registro más reciente. Sólo `heartrate` y `ring_battery_level` |
| `formato` | `json` o `csv`. Sobre un día real de `heartrate`, el CSV ocupa **56% menos** |

Y lo que la respuesta te dice cuando algo no salió redondo: `truncado` con
`continuar_desde` para reanudar, `campos_ignorados`,
`descartados_fuera_de_rango`, `columnas_desiguales`.

## Lo que este servidor NO hace

**No analiza.** Ni correlaciones, ni detección de anomalías, ni comparación de
periodos — que es justo donde otros servidores ponen su valor.

La razón: un promedio calculado aquí adentro llega al modelo como un número sin
su método. Sobre nueve años de datos reales, **tres de cada cuatro cambios entre
dos mediciones consecutivas caben dentro de la oscilación normal de la propia
métrica**. Un servidor que entrega «tu HRV subió 12%» sin decir cuánto oscila
sola esa métrica no está informando: está fabricando una señal.

Aquí se entregan los datos. El análisis va donde se pueda citar el método —
por ejemplo con [cotejo](https://github.com/proscar87/cotejo), que hace
exactamente esa distinción para biomarcadores de sangre.

## Las 19 colecciones

**Resúmenes diarios** — `daily_sleep`, `daily_readiness`, `daily_activity`,
`daily_stress`, `daily_spo2`, `daily_resilience`, `daily_cardiovascular_age`,
`vO2_max`

**El detalle que los puntajes esconden** — `sleep` (etapas, HRV, temperatura,
latencia), `sleep_time`, `workout`, `session`, `rest_mode_period`, `tag`,
`enhanced_tag`

**Alta resolución** — `heartrate`, `ring_battery_level`

**Sin rango** — `personal_info`, `ring_configuration`

Las de rango de fecha usan `AAAA-MM-DD`. `heartrate` y `ring_battery_level` usan
ISO 8601 con hora.

## Otros servidores MCP de Oura

En agosto de 2026 hay varios, y conviene ser exacto sobre en qué se diferencian.
[`benngermin/oura-mcp`](https://github.com/benngermin/oura-mcp) **pagina bien**,
con cursor reanudable. [`daveremy/oura-mcp`](https://github.com/daveremy/oura-mcp)
publicó el arreglo de `end_date` la misma semana que nosotros.
[`davidmosiah/oura-mcp`](https://github.com/davidmosiah/oura-mcp) tiene la
superficie MCP más completa. La paginación ya no distingue a nadie.

Lo que sí, hasta donde pudimos verificar: **el desfase a UTC de `workout` no
está documentado en ningún otro**, ni el rechazo de `latest` donde Oura lo
ignora, ni el aviso de campos que no se aplicaron. Y ninguno declara no analizar
como una postura.

## Privacy Policy

Este servidor corre **en tu máquina** y habla con **un solo servicio**: la API
de Oura. No hay backend nuestro, no hay telemetría, no hay analítica.

**Qué se recolecta.** Nada. Este software no recolecta datos. Los datos de salud
que pides van de la API de Oura a tu cliente MCP y no pasan por ningún otro
lado.

**Qué se guarda, y dónde.** Sólo tus credenciales, y sólo en tu máquina:

| | |
|---|---|
| Tokens de OAuth2 | `~/.config/oura-mcp/credenciales.json`, permisos `600` — o el llavero del sistema si tienes `keyring` |
| Token personal | Donde tú lo pongas: `OURA_PAT` o el archivo de `OURA_PAT_FILE` |

Ningún dato de salud se escribe en disco. No hay caché.

**Con quién se comparte.** Con nadie. La única conexión saliente es a
`api.ouraring.com`, con tu token, para traer lo que pediste. El uso que Oura
hace de tus datos se rige por
[su política de privacidad](https://ouraring.com/privacy-policy), no por ésta.

**Cuánto se retiene.** Las credenciales, hasta que las borres:
`oura-mcp --olvidar`, o borrando el archivo. Los datos de salud no se retienen —
viven en la respuesta y ya.

**Los diagnósticos no exponen nada.** `oura_revisar` reporta la longitud del
token, nunca el token; los nombres de los campos del perfil, nunca sus valores.
El token va envuelto en un tipo que no se imprime ni en una traza.

**Contacto.** [Issues del repositorio](https://github.com/proscar87/oura-mcp/issues).

## Licencia

MIT.

---

<!-- El registro de MCP exige esta línea en el README del paquete publicado en
     PyPI: es como comprueba que quien publica el servidor es el mismo que
     controla el paquete. Sin ella, `mcp-publisher publish` devuelve un 400. -->
mcp-name: io.github.proscar87/oura-mcp
