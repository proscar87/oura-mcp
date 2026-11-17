# oura-mcp, remote — for claude.ai, ChatGPT and anything that connects by URL

> **Experimental** as of 0.4.0 — see [what has and has not been verified](#what-has-and-has-not-been-verified).

The same server as the desktop extension, running as a Cloudflare Worker **on
your own Cloudflare account**, for **your own Oura account only**. There is no
shared instance: nobody else operates this, so nobody else holds your tokens or
sees your data.

The free Cloudflare plan is enough. Setup takes about ten minutes, once.

```
claude.ai / ChatGPT ──OAuth──▶ your Worker ──OAuth──▶ Oura
```

Apps that cannot do OAuth and only take a URL and one fixed token can be let in
too, with a token you choose: [off by default](#apps-that-only-take-a-fixed-token-optional).

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

Then the three required secrets. They never go in `wrangler.jsonc`:

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

## Apps that only take a fixed token (optional)

Some apps connect to a remote MCP server with a URL and **one fixed bearer
token**, and cannot open a login page — a custom connector in Meta's Muse and a
remote MCP tool in xAI's API are the two this was added for. For those, and only
if you turn it on, the Worker accepts a token of your own choosing in place of
its OAuth:

```
the app ──Authorization: Bearer <your token>──▶ your Worker ──OAuth──▶ Oura
```

**It is off until you set the secret.** With `MCP_BEARER_TOKEN` not set, the
Worker behaves exactly as described above and no fixed token is accepted.

1. **Sign in to Oura once, through OAuth.** The fixed token never signs in to
   Oura; it reads the session your own login left in the Worker. Connect
   claude.ai or ChatGPT as in step 4 — or any MCP client that does OAuth — and
   finish Oura's login. Until you have, every tool that reads your data answers
   that «this connector has no Oura session».
2. **Make a long random token and store it as a secret:**

   ```bash
   openssl rand -base64 32          # copy what it prints
   npx wrangler secret put MCP_BEARER_TOKEN
   ```

   It must be **at least 32 characters**. A shorter one is ignored and the mode
   stays off — a guessable token would be the only thing between the internet
   and your data. It never goes in `wrangler.jsonc`.
3. **Give the app** the same address as the others, `https://oura-mcp.<your-subdomain>.workers.dev/mcp`,
   and the token as its bearer token / API key. The Worker reads it from the
   `Authorization: Bearer …` header only, never from the URL.

To check it from a terminal, without any app:

```bash
curl -s https://oura-mcp.<your-subdomain>.workers.dev/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

**Know what you are turning on.** This token is a password to your Oura data
that does not expire and that no consent page stands in front of. Whoever holds
it reads what you can read — it is read-only, like everything here. It is stored
by the app you give it to, on that company's servers. So: one token, given only
to apps you use; never in a chat, a screenshot or a repository.

- **Change it**: `npx wrangler secret put MCP_BEARER_TOKEN` again. The old one
  stops working at once, in every app that had it.
- **Turn it off**: `npx wrangler secret delete MCP_BEARER_TOKEN`.

The apps connected through OAuth are not affected by either.

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
| The fixed token, if you set one | A Worker secret on your account — and in each app you gave it to |
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

- **The fixed token is opt-in, and only replaces the first layer.** OAuth is
  the default because its tokens are issued per app, expire, and are only
  handed out after you saw who was asking. A fixed token has none of that, so
  it exists only when you set it, is refused if it is short, and is compared in
  constant time. It does not weaken the owner check: it can only read the Oura
  session that an owner-checked login stored.

## What has and has not been verified

**Verified**, in CI on every push, against the real runtime (`wrangler dev`) and
the real OAuth library: app registration, the consent page and three forged
approvals, token exchange, the MCP endpoint with every tool, and the fixed
token (accepted when set, refused when altered, short or sent in the URL), in
sandbox mode. The Oura login, the owner check and token refresh are tested against a
fake of Oura (`tests/`).

**Not verified by this repository**: a real deployment signed into a real Oura
account, and claude.ai or ChatGPT completing the connection. **Nor any app
using the fixed token**: that Muse and xAI's API accept this Worker's address
and token is the premise it was built on, not something run or checked here —
which is why this page gives no menu paths for them. If you do any of these, an issue
saying how it went is the most useful thing you could send.
