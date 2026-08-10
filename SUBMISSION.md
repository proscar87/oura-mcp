# Claude desktop extension directory — submission answers

The form at <https://clau.de/desktop-extention-submission> is a Google Form
behind a sign-in, so it has to be filled from Oscar's account. Everything it
asks for is below, ready to paste.

**Extension name:** Oura

**Bundle:** `oura-mcp.mcpb` — <https://github.com/proscar87/oura-mcp/releases/latest>

**Repository:** <https://github.com/proscar87/oura-mcp>

**Privacy policy:** <https://github.com/proscar87/oura-mcp#privacy-policy>

**Short description**

> The Oura Ring v2 API as an MCP server. All 19 collections, three tools, and it
> paginates to the end so a partial answer never passes for a complete one.

**Long description**

> Oura's API does not return errors when it can't give you what you asked for.
> It returns something different, shaped like a correct response. This server
> corrects the four ways that happens, all measured against the real API.
>
> One local day of heart rate is 1,231 samples across 2 pages; a client that
> doesn't follow `next_token` returns 81% of them with nothing saying so. This
> one paginates to exhaustion and reports the page count rather than exposing a
> cursor as a tool parameter — a cursor makes pagination the model's job, and a
> model that forgets to ask again answers confidently off partial data.
>
> It also fixes the date range Oura applies inconsistently across collections,
> rejects `latest=true` where Oura would silently return everything, and names
> field projections Oura ignored.
>
> It deliberately performs no analysis: no correlations, no anomaly detection,
> no period comparison. An average computed inside the server reaches the model
> as a number without its method.

**Works without credentials?** Yes. It runs on Oura's official sample data out
of the box, and every sample response carries a `synthetic` key saying so, so
nothing can pass for the user's own health data.

**Credentials required for real data:** an Oura OAuth2 client ID and secret,
entered once in the extension's settings. Oura requires every application to be
registered; the settings spell out the exact redirect, trailing slash included.
Authorization itself happens in the browser via MCP URL elicitation — no
terminal.

**Data handling:** no telemetry, no analytics, no third-party services. Health
data is never written to disk. Credentials are stored locally at
`~/.config/oura-mcp/credenciales.json` with `0600` permissions and can be erased
with `oura-mcp --forget`.

**Tools:** `oura_collections`, `oura_query`, `oura_check` — all read-only.

**License:** MIT
