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

## Dónde está publicado — los tres, hechos

| | |
|---|---|
| GitHub | https://github.com/proscar87/oura-mcp — público, MIT, CI verde |
| PyPI | https://pypi.org/project/mcp-oura/ — **0.1.0 y 0.1.1** |
| Registro de MCP | `io.github.proscar87/oura-mcp` **v0.1.1**, listado y buscable |

El nombre de instalación es `mcp-oura` porque `oura-mcp` ya estaba tomado en
PyPI por un paquete 0.1.0 sin autor ni repositorio. El módulo que se importa
sigue siendo `oura_mcp`.

## Cómo se publica una versión nueva

```
# subir el número en pyproject.toml Y en server.json — tienen que coincidir
git tag v0.1.2 && git push origin v0.1.2
```

Eso corre las pruebas, publica en PyPI y luego en el registro. **No hay ningún
secreto configurado y no debe haberlo**: las dos publicaciones van por OIDC, con
una credencial de un solo uso que GitHub genera en el momento. El publicador
confiable de PyPI ya está dado de alta con estos datos:

```
dueño        proscar87
repositorio  oura-mcp
workflow     publicar.yml
environment  pypi
```

Si alguna vez alguien propone meter un token de PyPI en `secrets`, es un paso
atrás: sería una llave permanente con permiso de publicar en TODOS los proyectos
de la cuenta, viviendo en un lugar más.

## Tres cosas que costaron y no hay que repetir

**1. El registro tiene que esperar a PyPI.** Valida que la VERSIÓN exacta exista
en PyPI antes de aceptarla. Hubo un rato en que `registro` dependía de `pruebas`
en vez de `pypi` —un parche mientras faltaba el publicador confiable— y eso creó
una carrera: el registro terminaba en 5 segundos, buscaba la 0.1.1 y todavía no
existía. Un paso que valida contra otro no puede correr en paralelo con él.

**2. PyPI tarda en propagar** aunque el orden esté bien. Por eso el paso del
registro reintenta cinco veces con espera en vez de fallar a la primera.

**3. El registro exige una prueba de propiedad** en el README **del paquete
publicado en PyPI**: la línea `mcp-name: io.github.proscar87/oura-mcp`, que está
al final del README. Si se borra, la siguiente publicación al registro devuelve
un 400. No es decorativa.

**Y una que no es del proyecto pero costó un token:** NO uses `~/.pypirc`. El
9-ago un archivo mal formado —el token sin el encabezado `[pypi]`— hizo que el
parser de Python volcara el token completo a un transcript, y hubo que
revocarlo. Con el publicador confiable no hace falta ninguno.

## Lo que queda por hacer

- **Listas de la comunidad**: `awesome-mcp-servers`, mcp.so, Smithery. Sale
  gratis y es de donde viene la mayor parte del tráfico.
- **Composición segmental de nada de esto** — ver el README: el servidor no
  analiza a propósito.
- Si Oura agrega colecciones, se tocan en `colecciones.py` y nada más.

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
