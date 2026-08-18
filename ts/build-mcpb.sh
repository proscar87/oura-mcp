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
# THE PACKAGE IS SCOPED; the binary it installs is not. `npx mcpb` resolves only
# where the tool is already installed — globally, or in a node_modules nearby.
# Anywhere else npx asks the registry for a package literally named `mcpb`, gets
# a 404, and the build of the artifact the README recommends first dies on a
# machine that has done nothing wrong. It built here for three releases and
# failed on the first machine that had not installed it by hand.
#
# PINNED EXACTLY, not to a major. `pack` decides the bytes every client
# installs, and a minor is free to change which files go in — so `@2` promised
# «a release never discovers a packer change» and did not deliver it. Bumping
# this is one reviewable line, which is the point.
#
# NPM_CACHE reaches here too. This is the script's only registry download, and
# the failure path above advertises `NPM_CACHE=$(mktemp -d)` as THE remedy for a
# broken cache — advice that got you past `npm install` and then died ten lines
# later against the same poisoned cache.
npx ${NPM_CACHE:+--cache "$NPM_CACHE"} --yes @anthropic-ai/mcpb@2.1.2 \
    pack "$STAGE" "$OUT"

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
  | OURA_SANDBOX=1 node --unhandled-rejections=strict \
        "$VERIFY/server/dist/main.js" >"$VERIFY/out.jsonl" 2>"$VERIFY/err" || true
# `|| true` IS THE POINT, under `set -euo pipefail`. Without it a bundle that
# dies at startup takes the script down on this very line, and the three checks
# below — each with its own message and one with `cat "$VERIFY/err"` — never run.
# The build failed silently in exactly the case they were written for, which is
# the failure this file says at the top it exists to prevent. The greps decide
# pass or fail; node's exit code adds nothing they do not already catch.

grep -q '"serverInfo"' "$VERIFY/out.jsonl" \
  || { echo "the bundle did not complete the handshake" >&2; cat "$VERIFY/err" >&2; exit 1; }

# A REAL QUERY, not just the handshake. The bundle ships with sample data on by
# default, and sample data that does not announce itself is this package's own
# thesis committed against its own users. The handshake alone cannot see that —
# it shipped unmarked once precisely because nothing here asked for data.
grep -q 'SANDBOX MODE' "$VERIFY/out.jsonl" \
  || { echo "sandbox data came back UNMARKED — a model would report it as the user's own" >&2
       tail -c 400 "$VERIFY/out.jsonl" >&2; exit 1; }

# --unhandled-rejections=strict, because two separate process crashes were found
# in one week and both were a promise or an event nobody was listening to. Under
# the default mode a floating rejection is a warning on stderr that nobody reads;
# under strict it takes the process down here, in the build, instead of on
# someone's machine mid-authorization.

# The resource is surface too, and it shipped in a bundle before anything here
# asked for it. A capability nobody exercises is one nobody notices breaking.
grep -q 'daily_sleep' "$VERIFY/out.jsonl" \
  || { echo "the collections resource returned nothing" >&2; exit 1; }

echo "handshake ok, sandbox data marked, and the resource answers"
echo "==> ok"
