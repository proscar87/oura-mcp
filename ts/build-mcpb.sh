#!/usr/bin/env bash
# Builds the .mcpb — the one-click bundle for Claude Desktop.
#
# The bundle carries the compiled server AND its production dependencies, because
# Claude Desktop ships Node but installs nothing. Dev dependencies are excluded
# deliberately: with them the bundle is 78 MB, without them it's 3.
#
#     ./build-mcpb.sh          -> ../oura-mcp.mcpb
set -euo pipefail

cd "$(dirname "$0")"
OUT="${1:-../oura-mcp.mcpb}"
# Absolute from the start: the verification step cds elsewhere, and a relative
# path resolved from there points at nothing.
mkdir -p "$(dirname "$OUT")"
OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "==> compiling"
npx tsc

echo "==> staging"
mkdir -p "$STAGE/server"
cp -r dist "$STAGE/server/dist"
cp manifest.json icon.png "$STAGE/"

# A package.json with dependencies only: `npm install --omit=dev` needs it, and
# shipping the dev list would invite someone to install it.
node -e '
  const p = require("./package.json");
  require("fs").writeFileSync(process.argv[1] + "/server/package.json",
    JSON.stringify({ name: p.name, version: p.version, type: "module",
                     dependencies: p.dependencies }, null, 2));
' "$STAGE"

echo "==> installing production dependencies"
# NOT --silent: it swallows npm's error text, and this step already failed once
# with a corrupted cache while printing nothing but the exit code. A build that
# fails without saying why is the failure this whole repository is about.
if ! (cd "$STAGE/server" && npm install --omit=dev --no-audit --no-fund \
        ${NPM_CACHE:+--cache "$NPM_CACHE"} >"$STAGE/npm.log" 2>&1); then
  echo "npm install failed:" >&2
  cat "$STAGE/npm.log" >&2
  echo >&2
  echo "If it is the cache (EEXIST/EACCES under ~/.npm), retry with:" >&2
  echo "  NPM_CACHE=\$(mktemp -d) $0" >&2
  exit 1
fi

echo "==> packing"
npx mcpb pack "$STAGE" "$OUT"

echo
echo "==> verifying the packed bundle actually starts"
VERIFY="$(mktemp -d)"
trap 'rm -rf "$STAGE" "$VERIFY"' EXIT
(cd "$VERIFY" && unzip -q "$OUT")
# The handshake, not the source: the ugliest way an MCP server fails is by not
# completing it, and no unit test catches that.
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2026-07-28","capabilities":{},"clientInfo":{"name":"build","version":"1"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"oura_query","arguments":{"collection":"daily_sleep","day":"2026-01-15"}}}' \
  '{"jsonrpc":"2.0","id":3,"method":"resources/read","params":{"uri":"oura://collections"}}' \
  | OURA_SANDBOX=1 node "$VERIFY/server/dist/main.js" >"$VERIFY/out.jsonl" 2>"$VERIFY/err"

grep -q '"serverInfo"' "$VERIFY/out.jsonl" \
  || { echo "the bundle did not complete the handshake" >&2; cat "$VERIFY/err" >&2; exit 1; }

# A REAL QUERY, not just the handshake. The bundle ships with sample data on by
# default, and sample data that does not announce itself is this package's own
# thesis committed against its own users. The handshake alone cannot see that —
# it shipped unmarked once precisely because nothing here asked for data.
grep -q 'SANDBOX MODE' "$VERIFY/out.jsonl" \
  || { echo "sandbox data came back UNMARKED — a model would report it as the user's own" >&2
       tail -c 400 "$VERIFY/out.jsonl" >&2; exit 1; }

# The resource is surface too, and it shipped in a bundle before anything here
# asked for it. A capability nobody exercises is one nobody notices breaking.
grep -q 'daily_sleep' "$VERIFY/out.jsonl" \
  || { echo "the collections resource returned nothing" >&2; exit 1; }

echo "handshake ok, sandbox data marked, and the resource answers"
echo "==> ok"
