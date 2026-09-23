# oura-mcp, remote — for claude.ai, ChatGPT and anything that connects by URL

The same server as the desktop extension, running as a Cloudflare Worker **on
your own Cloudflare account**, for **your own Oura account only**. There is no
shared instance: nobody else operates this, so nobody else holds your tokens or
sees your data.

The free Cloudflare plan is enough. Setup takes about ten minutes, once.

```
claude.ai / ChatGPT ──OAuth──▶ your Worker ──OAuth──▶ Oura
```

## What you need

- A Cloudflare account (free).
- Node 22 or newer.
- An Oura application — the same kind the local server uses.

## 1. Register the Oura application

At [cloud.ouraring.com/oauth/applications](https://cloud.ouraring.com/oauth/applications),
create an application with this redirect URI, **trailing slash included** — Oura
rejects the form without it with `invalid_redirect_uri`:

```
https://oura-mcp.<your-subdomain>.workers.dev/callback/
```

Your `workers.dev` subdomain is shown in the Cloudflare dashboard under
*Workers & Pages*. If you don't know it yet, deploy first (step 3), read the URL
Wrangler prints, and come back.

## 2. Configure

```bash
git clone https://github.com/proscar87/oura-mcp.git
cd oura-mcp/ts && npm ci
cd worker && npm ci
npx wrangler login
```

Set your time zone in `wrangler.jsonc` — **required**. A Worker's clock is UTC,
and without it your evening reads as tomorrow:

```jsonc
"OURA_TIMEZONE": "America/Mexico_City"
```

Then the three secrets. They never go in `wrangler.jsonc`:

```bash
npx wrangler secret put OURA_CLIENT_ID
npx wrangler secret put OURA_CLIENT_SECRET
npx wrangler secret put OURA_OWNER_EMAIL     # the email of YOUR Oura account
```

`OURA_OWNER_EMAIL` is what makes this yours. After Oura's login the Worker
reads the account's email and turns away any other — and if the setting is
missing, it lets nobody in.

## 3. Deploy

```bash
npx wrangler deploy
```

Wrangler creates the storage it needs on the first deploy and prints your URL.

## 4. Connect

The address to give each app is your URL **followed by `/mcp`**:
`https://oura-mcp.<your-subdomain>.workers.dev/mcp`.

- **claude.ai** — *Settings → Connectors → Add custom connector*. Paste the
  address; leave the advanced OAuth fields empty.
- **ChatGPT** — *Settings → Apps → Advanced settings → Developer mode*, then
  create a connector with the address and **OAuth** as the authentication.

Each one opens this Worker's own page first. It shows **which app is asking and
exactly where the result will be sent**. Approve only if you started it from
that app just then. Then Oura's login, then you're back in the app.

## Try it before registering anything

```jsonc
"OURA_SANDBOX": "1"
```

serves Oura's sample data and skips Oura's login. Everything it returns is
marked `synthetic` — never anyone's data.

## What is stored, and where

| | |
|---|---|
| Your Oura tokens | A Durable Object on your Cloudflare account |
| The apps' tokens for this Worker | KV on your account, **hashed**; what they carry is encrypted |
| Your health data | **Nowhere.** Fetched from Oura per request, held only in the Worker's memory while it runs |

To disconnect everything: remove the connector in each app, and `npx wrangler
delete` removes the Worker and what it stored.

## Why it is built this way

- **One owner, checked after login.** A connector anyone could sign into with
  their own Oura account would make you the operator of a health-data service.
- **A consent page of its own.** Any app can register itself with this Worker.
  Oura skips its consent screen for an account that already approved, so
  without this page a link crafted by someone else could hand them your
  authorization. The approval is tied to the browser that saw the page.
- **Oura's tokens in a Durable Object, not in each app's grant.** Oura's refresh
  token is single-use. Two connected apps refreshing it at the same moment
  would lock you out; one object refreshes it, one request at a time.

## What has and has not been verified

**Verified**, in CI on every push, against the real runtime (`wrangler dev`) and
the real OAuth library: app registration, the consent page and three forged
approvals, token exchange, and the MCP endpoint with every tool, in sandbox
mode. The Oura login, the owner check and token refresh are tested against a
fake of Oura (`tests/`).

**Not verified by this repository**: a real deployment signed into a real Oura
account, and claude.ai or ChatGPT completing the connection. If you do either,
an issue saying how it went is the most useful thing you could send.
