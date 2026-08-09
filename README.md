# oura-mcp

La API v2 de [Oura](https://ouraring.com) como servidor [MCP](https://modelcontextprotocol.io).
Las 19 colecciones, cuatro herramientas, cero dependencias fuera del SDK de MCP.

**Lo que lo distingue: pagina.** Suena a poco y es todo el punto — ver abajo.

---

## El problema

Oura entrega sus respuestas así:

```json
{ "data": [ ... ], "next_token": "eyJ0eXAiOi..." }
```

Si `next_token` viene y no lo sigues, recibes la primera página y **nada te
avisa**. La respuesta es un JSON válido, con datos reales, que se ve completo.

En un día cualquiera, `heartrate` —que muestrea cada cinco minutos— devuelve
**1,246 muestras repartidas en 2 páginas**. Un cliente que no pagina te entrega
la primera y tú te quedas creyendo que ésa es la frecuencia cardiaca de tu día.
Un mes son ~37,000 muestras: ahí la fracción que ves es minúscula, y sigue sin
avisar.

Revisamos los siete servidores MCP de Oura publicados en GitHub en agosto de
2026. **El más completo de todos no pagina**: en su cliente, `next_token`
aparece una sola vez, en la definición del tipo. Los dos más estrellados están
literalmente muertos — creados y abandonados el mismo día, con 28 y 31 minutos
entre el primer commit y el último.

Por eso existe éste.

## Instalación

```bash
pip install mcp-oura
```

*(El nombre de instalación es `mcp-oura`: `oura-mcp` ya estaba tomado en PyPI por
un paquete 0.1.0 sin autor ni repositorio. El módulo que se importa sigue siendo
`oura_mcp`.)*

Necesitas un *Personal Access Token*, que se saca en
[cloud.ouraring.com/personal-access-tokens](https://cloud.ouraring.com/personal-access-tokens).
No hay OAuth, no hay callback, no hay aplicación que registrar: es un token y ya.

```bash
export OURA_PAT="tu-token"
oura-mcp --revisar
```

`--revisar` es el autodiagnóstico: dice si el token está puesto y si Oura
responde, **sin devolver el token ni un solo dato de salud**. Reporta la longitud
del token, nunca el token. Los mensajes de error se copian y se pegan en chats y
en issues; no tienen por qué arrastrar nada más.

### Conectarlo a Claude Code

```bash
claude mcp add -s user oura --env OURA_PAT=tu-token -- /ruta/a/oura-mcp
```

Mejor aún, con el token en un archivo aparte y no en la configuración:

```bash
printf '%s' "tu-token" > ~/.oura_pat && chmod 600 ~/.oura_pat
claude mcp add -s user oura --env OURA_PAT_FILE=$HOME/.oura_pat -- /ruta/a/oura-mcp
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
      "command": "/ruta/a/oura-mcp",
      "env": { "OURA_PAT_FILE": "/Users/tu-usuario/.oura_pat" }
    }
  }
}
```

## Las herramientas

| | |
|---|---|
| `oura_colecciones` | Las 19 con qué trae cada una y qué parámetros pide |
| `oura_consultar` | Trae una colección completa en un rango, paginando hasta el final |
| `oura_revisar` | Autodiagnóstico sin exponer nada |

**Tres, no diecinueve.** Un servidor con una herramienta por colección obliga al
modelo a elegir entre 19 nombres parecidos antes de saber qué contienen. Aquí la
colección es un parámetro y el catálogo se consulta cuando hace falta.

Si el rango pedido excede el tope de páginas, la respuesta trae una clave
`truncado` que lo dice con todas sus letras. **Un resultado incompleto que no se
declara incompleto es peor que un error**: se ve igual que uno completo.

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

## Licencia

MIT.

---

<!-- El registro de MCP exige esta línea en el README del paquete publicado en
     PyPI: es como comprueba que quien publica el servidor es el mismo que
     controla el paquete. Sin ella, `mcp-publisher publish` devuelve un 400. -->
mcp-name: io.github.proscar87/oura-mcp
