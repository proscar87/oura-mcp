# Para el siguiente agente

Estado al **9 de agosto de 2026**. Lee esto antes de tocar nada.

## Qué es esto

Un servidor MCP sobre la API v2 de Oura. **Su única razón de existir es que
pagina.** De los siete servidores MCP de Oura publicados en GitHub, el más
completo no lo hace: en su cliente `next_token` aparece una sola vez, en la
definición del tipo. Los dos más estrellados están muertos — creados y
abandonados el mismo día, con 28 y 31 minutos de vida.

Si alguna vez alguien propone "simplificar" el bucle de paginación de
`cliente.obtener()`, la respuesta es no. Ese bucle es el producto.

## Dónde está publicado

| | |
|---|---|
| GitHub | https://github.com/proscar87/oura-mcp — público, MIT |
| PyPI | https://pypi.org/project/mcp-oura/ — **v0.1.0 publicada** |
| Registro de MCP | **PENDIENTE**, ver abajo |

El nombre de instalación es `mcp-oura` porque `oura-mcp` ya estaba tomado en
PyPI por un paquete 0.1.0 sin autor ni repositorio. El módulo que se importa
sigue siendo `oura_mcp`.

## Lo que falta, en orden

### 1. Publicar la v0.1.1 en PyPI

Está lista en el repo: `pyproject.toml` y `server.json` ya dicen `0.1.1`, y el
README lleva al final la línea `mcp-name: io.github.proscar87/oura-mcp`, que es
lo que faltaba (ver punto 2).

**Dos caminos.** El bueno es el primero:

**a) Publicador confiable (sin token).** Falta un formulario de una sola vez en
pypi.org → *Publishing* → el proyecto `mcp-oura` → *Add a new publisher*. Los
datos exactos los escupió el propio fallo del flujo:

```
dueño        proscar87
repositorio  oura-mcp
workflow     publicar.yml
environment  pypi
```

Con eso, publicar es `git tag v0.1.1 && git push origin v0.1.1` y no existe
ningún secreto que rotar.

**b) A mano, con token.** Oscar tiene cuenta. **Que lo corra ÉL en Terminal.app**
— no en el `!` de Claude Code, que no da terminal interactiva:

```
cd ~/Developer/oura-mcp && python -m build && python -m twine upload dist/*
```

`twine` pregunta usuario (`__token__`) y contraseña (el token). No lo guardes en
`~/.pypirc`: el 9-ago un archivo mal formado hizo que el parser volcara el token
completo al transcript de la sesión y hubo que revocarlo.

### 2. Publicar en el registro de MCP

El flujo ya está escrito (`.github/workflows/publicar.yml`, job `registro`) y el
**login por OIDC ya funciona** — se verificó, devuelve `✓ Successfully logged
in`. Lo único que faltaba era la prueba de propiedad: el registro exige que el
README **del paquete publicado en PyPI** contenga la línea

```
mcp-name: io.github.proscar87/oura-mcp
```

Ya está en el README de este repo, pero **la v0.1.0 que está en PyPI no la
tiene**. Por eso el orden importa: primero sube la v0.1.1, luego dispara el
registro (`gh workflow run publicar.yml --ref main`).

### 3. Después de eso

- Revocar cualquier token de PyPI que quede: con el publicador confiable ya no
  hace falta ninguno, y los que Oscar generó tienen alcance de **cuenta
  completa**.
- Listas de la comunidad (`awesome-mcp-servers`, mcp.so, Smithery). Sale gratis
  y es de donde viene la mayor parte del tráfico.

## Decisiones que NO hay que revertir

**Tres herramientas, no diecinueve.** Una por colección obliga al modelo a
elegir entre 19 nombres parecidos antes de saber qué contienen.

**No analiza.** Ni correlaciones, ni anomalías, ni comparación de periodos — que
es donde otros servidores ponen su valor. Un promedio calculado adentro llega al
modelo como un número sin su método, y sobre nueve años de datos reales tres de
cada cuatro cambios entre mediciones consecutivas son ruido. Entregar «tu HRV
subió 12%» sin decir cuánto oscila sola esa métrica no es informar: es fabricar
una señal. El análisis va donde se pueda citar el método — ver
[cotejo](https://github.com/proscar87/cotejo).

**El token puede vivir en un archivo** (`OURA_PAT_FILE`, permisos 600) y no en
la configuración del cliente MCP. Un servidor MCP se registra en un JSON que se
respalda, se sincroniza y se comparte al pedir ayuda.

**`.garita.yml` se queda.** [Garita](https://github.com/proscar87/garita) es la
herramienta de Oscar que bloquea commits con datos personales o credenciales, y
corre en el CI. Aquí no hay tokens que proteger —el PAT vive en el entorno— pero
sí hay un riesgo real y específico: que alguien pegue una respuesta **de verdad**
de Oura como ejemplo en el README o en una prueba. `personal_info` devuelve
correo, edad, peso y estatura. Ése es el escenario que Garita atrapa.
La clave `exenciones` va **omitida**, no escrita como lista vacía: `exenciones:
[]` tropieza con el parser de Garita v0, que la lee como la cadena `"[]"`.

## Cómo se prueba

```
python -m pytest -q          # 14 pruebas, ninguna toca la red
```

Las pruebas sustituyen la API por una falsa que sirve páginas, lo que permite
probar la paginación contra un caso que en la vida real requeriría un mes de
datos. **Un CI que necesita el token de alguien para pasar no es un CI: es una
dependencia de esa persona.** No agregues pruebas que salgan a internet.

Para probar contra Oura de verdad, con el token de Oscar en `~/.oura_pat`:

```
OURA_PAT_FILE=~/.oura_pat python -m oura_mcp --revisar
```

## Contexto que no se ve en el código

Esto salió de auditar el panel de salud de Oscar (`~/Developer/panel-salud`),
donde el mismo modo de falla —datos truncados que se ven completos— apareció
tres veces: PostgREST ignorando `limit` y cortando en 1,000 filas, y el
parámetro `meastypes` de Withings devolviendo 13 de 30 tipos pedidos sin error
ni aviso. Ese último se diagnosticó mal durante horas como «suscripción
vencida». Por eso este paquete prefiere gritar antes que entregar de menos en
silencio: si se topa con el tope de páginas, la respuesta trae `truncado`
diciéndolo.
