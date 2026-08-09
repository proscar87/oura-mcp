# Para el siguiente agente

Estado al **9 de agosto de 2026, ~06:00**. Lee esto antes de tocar nada.

## Qué es esto

Un servidor MCP sobre la API v2 de Oura. **Su razón de existir es que Oura
entrega de menos sin avisar, y aquí se corrige.**

Ojo con cómo se cuenta eso, porque cambió. La versión anterior de este archivo
decía que el diferenciador era paginar, y que «de los siete servidores MCP de
Oura, el más completo no pagina». **Eso ya no es cierto**:
`benngermin/oura-mcp` pagina bien, y con cursor reanudable. La paginación es hoy
la línea de base, no la ventaja. No repitas esa frase.

Lo que sí sostiene el proyecto son **cuatro fallas silenciosas de la misma
familia**, medidas contra la API real y corregidas aquí:

| | La falla | Dónde vive el arreglo |
|---|---|---|
| 1 | `next_token` sin seguir → recibes una fracción. Un día de `heartrate` son 1,231 muestras en 2 páginas | el bucle de `cliente.obtener()` |
| 2 | `end_date` es inconsistente **entre colecciones**, y `workout` se filtra por fecha UTC reportando `day` local | `MARGEN_DIAS` y `_recortar()` |
| 3 | `latest=true` donde no aplica → Oura devuelve la colección **entera** | `CON_ULTIMO`, se rechaza antes de la red |
| 4 | `fields=inventado` → devuelve el registro completo, sin proyectar | `_campos_ignorados()` |

Si alguien propone «simplificar» cualquiera de esas cuatro, la respuesta es no.
Son el producto.

## Dónde está publicado

| | |
|---|---|
| GitHub | https://github.com/proscar87/oura-mcp — público, MIT, CI verde |
| PyPI | https://pypi.org/project/mcp-oura/ — 0.1.0 y 0.1.1 |
| Registro de MCP | `io.github.proscar87/oura-mcp` v0.1.1, `active`, buscable |

El nombre de instalación es `mcp-oura` porque `oura-mcp` ya estaba tomado en
PyPI por un paquete 0.1.0 sin autor ni repositorio. El módulo que se importa
sigue siendo `oura_mcp`.

**Nada de lo hecho esta madrugada está publicado todavía.** El repo va muy por
delante de la 0.1.1 que vive en PyPI.

## Cómo se publica una versión nueva

```
# subir el número en pyproject.toml Y en server.json — tienen que coincidir
git tag v0.2.0 && git push origin v0.2.0
```

Eso corre las pruebas, publica en PyPI y luego en el registro. **No hay ningún
secreto configurado y no debe haberlo**: las dos publicaciones van por OIDC, con
una credencial de un solo uso que GitHub genera en el momento. El publicador
confiable de PyPI ya está dado de alta con `proscar87` / `oura-mcp` /
`publicar.yml` / environment `pypi`.

Tres cosas que costaron y no hay que repetir: el paso del registro **tiene que
esperar a PyPI** (valida que la versión exacta exista) y reintenta mientras el
índice propaga; el registro exige la línea `mcp-name: io.github.proscar87/oura-mcp`
en el README **del paquete publicado**, y borrarla devuelve un 400. Y no uses
`~/.pypirc`: un archivo mal formado hizo que el parser volcara un token completo
a un transcript.

## Lo que bloquea, y es tuyo

Dos decisiones que un agente no debe tomar solo:

1. **Publicar la v0.2.0.** Está todo listo: las seis declaraciones de versión
   coinciden, el CHANGELOG está escrito, el wheel se construye. Falta
   `git tag v0.2.0 && git push origin v0.2.0`, que dispara PyPI y el registro.
2. **El `.mcpb`.** Medido: el binario de PyInstaller sirve con `--onedir`
   (0.41 s tras la primera vez) pero pide notarización de Apple, CI en dos
   plataformas y 45 MB por plataforma. TypeScript sale más barato *si el
   objetivo es Claude Desktop*. Y el plugin de Claude Code ya da instalación de
   un comando sin nada de eso. **La pregunta es de alcance, no técnica.**

## Lo que ya está hecho (v0.2 y v0.3)

Ocho puntos de corrección y OAuth2 completo. **121 pruebas, ninguna toca la red.**
El detalle largo, con lo medido, está en `ROADMAP.md`. Lo que hay que saber para
no romperlo:

- **`OURA_SANDBOX=1`** apunta a las rutas espejo de Oura, que son oficiales y
  aceptan cualquier cadena como `Authorization`. Sirve para instalar y ver el
  servidor andar sin credenciales. **No sirve para medir el comportamiento de la
  API**: es un *generador*, no un filtro — devuelve `n-1` registros para
  cualquier ventana y cero para una de una hora que contiene una muestra. Medir
  ahí la semántica de las fechas da respuestas equivocadas. Ya pasó una vez, en
  la primera versión del ROADMAP.
- **OAuth2** en `credenciales.py` y `autorizar.py`. El refresh token de Oura es
  **de un solo uso**: `refrescar()` guarda antes de devolver, de forma atómica.
  No muevas esa línea. Si dos procesos refrescan a la vez —dos herramientas MCP
  en paralelo— el que pierde la carrera relee lo guardado en vez de dar la
  sesión por perdida.
- **El `state` del callback se verifica** con `compare_digest`. Sin eso,
  cualquier página abierta en el navegador del usuario puede mandarle un código
  de autorización de otra cuenta.
- **`Secreto`** envuelve el token: su `repr` dice `<secreto de N caracteres>` y
  sacar el valor exige `.revelar()`.
- **El flujo de OAuth vive en la terminal**, nunca dentro del servidor MCP. Uno
  que habla por stdin/stdout no puede abrir un navegador ni pedirle nada a
  nadie.

## Lo que falta, en orden

### v0.4 — Instalación de un clic
- `uvx --from mcp-oura oura-mcp` ya está en el README. Falta publicar una
  versión que lo respalde.
- Plugin de Claude Code: un `.claude-plugin/marketplace.json`.
- **El `.mcpb`**, y ahí está la decisión difícil. Anthropic empaqueta Node con
  Claude Desktop; Python no. Las opciones y su costo están en `ROADMAP.md`,
  §v0.4. La recomendación es binario con PyInstaller —conserva el trabajo hecho—
  pero conviene decir en voz alta que **si el listado en Claude es la meta real,
  TypeScript es el camino que el propio Anthropic recomienda**.

### v0.5 — Directorio de conectores de Claude
La puerta viable es la **extensión de escritorio (MCPB)**: formulario aparte, sin
requisito de organización Team. Falta política de privacidad en el README, ícono
512×512, y el `.mcpb`. Las anotaciones de herramienta que exige ya están.

La otra puerta —conector remoto— **exige organización Team o Enterprise** y
hospedar datos de salud de terceros. Es una decisión, no un pendiente.

### Gratis y para ayer
`smithery.yaml`, `glama.json`, `llms.txt`, y PRs a `awesome-mcp-servers` y
mcp.so. Es de donde viene la mayor parte del tráfico.

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

**Cero dependencias fuera del SDK de MCP.** No es estética: es lo que hace
viable empaquetar esto como binario para Claude Desktop, que es el hito v0.4.
Por eso `keyring` se importa con `try` y nunca se declara — aquí está instalado,
pero viene de `twine`, no de `mcp`, y un usuario no lo tendría.

**El secreto no vive en la configuración del cliente MCP.** `OURA_PAT_FILE`, o
el archivo 0600 de OAuth. Un servidor MCP se registra en un JSON que se
respalda, se sincroniza y se comparte al pedir ayuda.

**`.garita.yml` se queda.** [Garita](https://github.com/proscar87/garita) bloquea
commits con datos personales o credenciales, y corre en el CI. Aquí el riesgo
real y específico es que alguien pegue una respuesta **de verdad** de Oura como
ejemplo en el README o en una prueba: `personal_info` devuelve correo, edad,
peso y estatura. La clave `exenciones` va **omitida**, no escrita como lista
vacía: `exenciones: []` tropieza con el parser de Garita v0, que la lee como la
cadena `"[]"`.

## Cómo se prueba

```
python -m pytest -q          # 121 pruebas, ninguna toca la red
```

**Un CI que necesita el token de alguien para pasar no es un CI: es una
dependencia de esa persona.** No agregues pruebas que salgan a internet al CI
obligatorio.

Lo que sí sale a internet vive aparte y nunca bloquea un PR:

```
python herramientas/revisar_deriva.py   # ¿siguen existiendo las 19? (sandbox, sin credenciales)
```

Corre semanal por `.github/workflows/deriva.yml`. Atrapa una colección
renombrada o retirada; **no** atrapa una nueva — el sandbox no se puede
enumerar, y el script lo dice en voz alta. Un chequeo que aparenta cubrir lo que
no cubre es peor que no tenerlo.

Para probar contra Oura de verdad, con el token de Oscar en `~/.oura_pat`:

```
OURA_PAT_FILE=~/.oura_pat python -m oura_mcp --revisar
```

**Al medir contra la API real, imprime sólo cuentas y nombres de campo, nunca
valores.** No es ceremonia: los transcripts se pegan en otros lados.

## Contexto que no se ve en el código

Esto salió de auditar el panel de salud de Oscar (`~/Developer/panel-salud`),
donde el mismo modo de falla —datos truncados que se ven completos— apareció
tres veces: PostgREST ignorando `limit` y cortando en 1,000 filas, y el
parámetro `meastypes` de Withings devolviendo 13 de 30 tipos pedidos sin error
ni aviso. Ese último se diagnosticó mal durante horas como «suscripción
vencida».

Resulta que Oura hace lo mismo en cuatro lugares distintos. La tesis aplicaba en
más sitios de los que decía.
