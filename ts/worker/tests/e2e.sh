#!/usr/bin/env bash
# The whole remote flow against the real Worker in workerd, in sandbox mode:
# the OAuth provider, this Worker's consent screen, and Oura's sample API.
#
#   npx wrangler dev --port 8787 --var OURA_SANDBOX:1 --var OURA_TIMEZONE:America/Mexico_City
#   ./tests/e2e.sh
#
# What sandbox cannot reach — Oura's login, the owner check, the refresh — is
# in authorize.test.ts and tokens.test.ts, against fakes. Say so rather than
# let a green run here imply more than it tested.
set -euo pipefail
B="${OURA_E2E_BASE:-http://localhost:8787}"
J=$(mktemp -d)
fail() { echo "FAIL: $*" >&2; exit 1; }
eq() { [[ "$1" == "$2" ]] || fail "$3: expected «$2», got «$1»"; echo "ok   $3"; }
has() { [[ "$1" == *"$2"* ]] || fail "$3: «$2» not in «${1:0:300}»"; echo "ok   $3"; }
code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }

eq "$(code -X POST "$B/mcp")" 401 "no token, no entry"
has "$(curl -s -D - -o /dev/null -X POST "$B/mcp")" "resource_metadata=" "the 401 points at the metadata"

REG=$(curl -s -X POST "$B/register" -H 'content-type: application/json' \
  -d '{"client_name":"E2E <b>Client</b>","redirect_uris":["http://localhost:9999/cb"],"token_endpoint_auth_method":"none"}')
CID=$(python3 -c "import json,sys;print(json.load(sys.stdin)['client_id'])" <<<"$REG")

VER=abcdefghijklmnopqrstuvwxyz0123456789abcdefghijk
CH=$(printf %s "$VER" | openssl dgst -sha256 -binary | openssl base64 | tr '+/' '-_' | tr -d '=')
AU="$B/authorize?response_type=code&client_id=$CID&redirect_uri=http%3A%2F%2Flocalhost%3A9999%2Fcb&code_challenge=$CH&code_challenge_method=S256&state=st1"

curl -s -c "$J/c" -D "$J/h" "$AU" -o "$J/page"
has "$(cat "$J/h")" "SameSite=Lax" "the consent cookie is Lax"
has "$(cat "$J/h")" "frame-ancestors 'none'" "the consent page cannot be framed"
has "$(cat "$J/page")" "localhost:9999/cb" "the consent page names where the result goes"
has "$(cat "$J/page")" "E2E &lt;b&gt;Client&lt;/b&gt;" "the client's own name is escaped"
N=$(grep -o 'name="nonce" value="[^"]*"' "$J/page" | cut -d'"' -f4)

F=(-X POST "$B/authorize" -d "nonce=$N&decision=approve")
eq "$(code -b "$J/c" "${F[@]}")" 403 "an approval with no Origin is refused"
eq "$(code -b "$J/c" -H 'origin: https://evil.example' "${F[@]}")" 403 "an approval from another site is refused"
eq "$(code -H "origin: $B" "${F[@]}")" 403 "an approval without the page's cookie is refused"

LOC=$(curl -s -o /dev/null -w "%{redirect_url}" -b "$J/c" -H "origin: $B" "${F[@]}")
has "$LOC" "state=st1" "the approval returns the client's state"
CODE=$(python3 -c "import urllib.parse,sys;print(urllib.parse.parse_qs(urllib.parse.urlparse(sys.argv[1]).query)['code'][0])" "$LOC")
eq "$(code -b "$J/c" -H "origin: $B" "${F[@]}")" 400 "an approval cannot be replayed"

TOK=$(curl -s -X POST "$B/token" -d "grant_type=authorization_code&code=$CODE&client_id=$CID&redirect_uri=http%3A%2F%2Flocalhost%3A9999%2Fcb&code_verifier=$VER")
AT=$(python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])" <<<"$TOK")

H=(-H "authorization: Bearer $AT" -H 'content-type: application/json' -H 'accept: application/json, text/event-stream')
rpc() { curl -s "${H[@]}" -X POST "$B/mcp" -d "$1"; }
tool() { rpc "{\"jsonrpc\":\"2.0\",\"id\":9,\"method\":\"tools/call\",\"params\":{\"name\":\"$1\",\"arguments\":$2}}" |
         python3 -c "import json,sys;print(json.load(sys.stdin)['result']['content'][0]['text'])"; }

has "$(rpc '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"e2e","version":"1"}}}')" '"name":"oura"' "initialize"
TOOLS=$(rpc '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | python3 -c "import json,sys;print(','.join(t['name'] for t in json.load(sys.stdin)['result']['tools']))")
eq "$TOOLS" "oura_collections,oura_query,oura_today,oura_compare,oura_relate,oura_check" "tools/list"
Q=$(tool oura_query '{"collection":"daily_sleep","start":"2026-01-01","end":"2026-01-03"}')
has "$Q" '"synthetic"' "sample data says it is sample data"
has "$Q" '"n": 3' "a three-day range is three records"
has "$(tool oura_check '{}')" '"oura_responds": true' "oura_check reaches Oura"
C=$(tool oura_compare '{"metric":"daily_readiness.score","a_start":"2026-03-01","a_end":"2026-03-14","b_start":"2026-03-15","b_end":"2026-03-28"}')
has "$C" '"verdict"' "oura_compare answers with a verdict"
has "$C" '"synthetic"' "and says the numbers it compared are sample data"
X=$(tool oura_relate '{"x":"daily_activity.steps","y":"daily_readiness.score","start":"2026-01-01","end":"2026-04-30","lag":1}')
has "$X" '"verdict"' "oura_relate answers with a verdict"
has "$X" '"synthetic"' "and says the numbers it related are sample data"
echo "all passed"
