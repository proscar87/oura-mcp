/**
 * The two pages a person ever sees from this Worker.
 *
 * EVERYTHING FROM THE CLIENT IS ESCAPED. A client picks its own name and
 * redirect URI when it registers, so both are attacker-controlled text on the
 * one page whose job is to show the truth about who is asking.
 */

const esc = (s: string) => s.replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

// `frame-ancestors 'none'`: a consent button inside someone else's frame can be
// clicked by someone who never saw it (clickjacking).
const HEADERS = {
  "content-type": "text/html; charset=utf-8",
  "cache-control": "no-store",
  "content-security-policy":
    "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
  "x-frame-options": "DENY",
  "referrer-policy": "no-referrer",
};

const shell = (title: string, body: string) =>
  `<!doctype html><html lang="en"><meta charset="utf-8">` +
  `<meta name="viewport" content="width=device-width,initial-scale=1">` +
  `<title>${esc(title)} · oura-mcp</title>` +
  `<body style="font-family:system-ui,sans-serif;max-width:34rem;margin:4rem auto;` +
  `padding:0 1rem;line-height:1.5;color:#1a1a1a;background:#fff">` +
  `<h1 style="font-size:1.4rem">${esc(title)}</h1>${body}</body></html>`;

export function messagePage(status: number, title: string, text: string): Response {
  return new Response(shell(title, `<p>${esc(text)}</p>`), { status, headers: HEADERS });
}

export function consentPage(o: { nonce: string; clientName: string; redirectUri: string;
                                 sandbox: boolean; cookie: string }): Response {
  let host: string;
  try {
    host = new URL(o.redirectUri).host;
  } catch {
    host = o.redirectUri;
  }
  const what = o.sandbox
    ? "<p><strong>Sample data mode.</strong> It will see Oura's synthetic data, not anyone's.</p>"
    : "<p>It will be able to <strong>read</strong> your Oura data: sleep, readiness, " +
      "activity, heart rate, workouts and the rest. It cannot change anything.</p>";
  const body =
    `<p><strong>${esc(o.clientName)}</strong> wants to connect to your Oura data.</p>` +
    what +
    `<p>If you approve, the result goes to:</p>` +
    `<p style="font-family:ui-monospace,monospace;background:#f3f3f3;padding:.5rem;` +
    `word-break:break-all"><strong>${esc(host)}</strong><br>${esc(o.redirectUri)}</p>` +
    `<p>Approve only if you started this from that app just now. ` +
    `If you did not, deny — someone may be trying to use your account.</p>` +
    `<form method="post" action="/authorize" style="display:flex;gap:.75rem">` +
    `<input type="hidden" name="nonce" value="${esc(o.nonce)}">` +
    `<button name="decision" value="approve" style="padding:.6rem 1.2rem">Approve</button>` +
    `<button name="decision" value="deny" style="padding:.6rem 1.2rem">Deny</button>` +
    `</form>`;
  const h = new Headers(HEADERS);
  h.append("set-cookie", o.cookie);
  return new Response(shell("Connect Oura", body), { status: 200, headers: h });
}
