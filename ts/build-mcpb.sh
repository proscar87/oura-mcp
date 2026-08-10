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
(cd "$STAGE/server" && npm install --omit=dev --silent --no-audit --no-fund ${NPM_CACHE:+--cache "$NPM_CACHE"})

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
  | OURA_SANDBOX=1 node "$VERIFY/server/dist/main.js" \
  | head -c 200
echo
echo "==> ok"
