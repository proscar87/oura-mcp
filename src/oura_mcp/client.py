"""Client for the Oura v2 API. No dependencies: standard library only.

THIS FILE IS THE PRODUCT. Oura never returns an error when it can't give you
what you asked for: it returns something different, shaped like a correct
response. These are the four we found by measuring against the real API, and
that are corrected here:

  1. Not following `next_token` returns a fraction. One local day of `heartrate`
     is 1,231 samples across 2 pages; a client that doesn't paginate gets
     1,000 — 81% — looking complete. A month is ~37,000.
  2. `end_date` is INCONSISTENT ACROSS COLLECTIONS, and `workout` filters by UTC
     date while reporting `day` in local time. Asking for a single day returned
     ZERO records.
  3. `latest=true` where it doesn't apply → Oura returns the entire collection.
  4. `fields=made_up` → returns the complete record, no projection.

And a third exit from the loop that nearly got away: if Oura repeats the same
`next_token`, that's a cycle. Without detecting it, the client made 50 identical
requests and warned "shorten the range" — useless advice, because shortening
doesn't stop the API from repeating itself.
"""

from __future__ import annotations

import csv
import datetime
import email.utils
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .collections import BASE, WITH_DATE, WITH_LATEST, WITHOUT_SANDBOX, shape

TIMEOUT = 30
PAGE_LIMIT = 50          # ~50k records; more than that is a usage error
RETRIES_429 = 2          # bounded: this runs inside a conversation
MAX_WAIT = 8.0           # seconds; not even Oura's `Retry-After` gets more

# How many characters before the response comments on itself. 50,000 is roughly
# 12,000 tokens: enough to matter, little enough not to nag. Measured: 30 days of
# `daily_activity` is 252,000, and 92% of it is a single field.
SIZE_WARNING = 50_000

# Extra days requested on each side before trimming. TWO, not one: `workout` is
# exclusive at the end AND skewed to UTC, and the two stack. The largest UTC
# offset in the world is ±14 h — one day — and the exclusivity costs another.
# Two covers any timezone.
EXTRA_DAYS = 2

# Keys a record's day can be read from, in order of confidence. `day` is on
# almost all of them; `start_day` belongs to rest_mode_period and enhanced_tag;
# the time-bearing ones are cut to ten characters.
_DAY_KEYS = ("day", "start_day")
_TIME_KEYS = ("timestamp", "start_time", "bedtime_start")


class OuraError(RuntimeError):
    """A failure talking to Oura. NEVER carries the token in its message."""


class Secret:
    """A token that can't be printed by accident. Ask for it with `reveal()`.

    A plain `str` holding a token leaks through too many places: the `repr` of
    local variables that some traceback formatters print, a debug `print` that
    was left behind, an exception dragging its context along, an f-string
    written in a hurry.

    This already cost a token once here — a malformed `~/.pypirc` made the parser
    dump a full token into a transcript — and the lesson wasn't "be more
    careful": it was that care can't be sustained by hand. With this class,
    printing it by accident is impossible; revealing it is an explicit call that
    shows up in the code and greps cleanly.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __len__(self) -> int:
        return len(self._value)

    def __repr__(self) -> str:
        return f"<secret, {len(self._value)} characters>"

    __str__ = __repr__


SYNTHETIC = (
    "SANDBOX MODE: this is Oura's sample data, not this person's. Do not "
    "report these numbers as their own. To see real data, turn off the "
    "sample-data setting and connect an Oura account."
)
"""On every sandbox response. Sample data that reads as real is the exact
failure this server exists to correct, so it says so in band, where a model
must see it — not in the documentation, where nobody reads it."""


def in_sandbox() -> bool:
    """Is `OURA_SANDBOX` set? Any value except empty, `0`, `no`, `false`."""
    v = (os.environ.get("OURA_SANDBOX") or "").strip().lower()
    return bool(v) and v not in ("0", "no", "false")


def base() -> str:
    """Where requests go. Sandbox, explicit override, or the real Oura.

    THE SANDBOX IS OFFICIAL, not a trick: it's in Oura's OpenAPI spec with 34
    mirror routes, and it accepts ANY string as `Authorization`. That lets you
    install the server, watch it work and learn the shape of the data BEFORE
    fighting with authentication — which stopped being a one-minute errand when
    Oura deprecated personal tokens in December 2025.

    What the sandbox is NOT good for is measuring API behavior: it's a
    GENERATOR, not a filter. It returns n-1 records for any window, and zero for
    a one-hour window that contains a sample. Measuring date semantics there
    gives wrong answers — that already happened once.
    """
    override = (os.environ.get("OURA_API_BASE_URL") or "").strip()
    if override:
        return override.rstrip("/")
    if in_sandbox():
        return BASE.replace("/v2/usercollection", "/v2/sandbox/usercollection")
    return BASE


def _token() -> Secret:
    """The credential: sandbox, personal token, or OAuth2, in that order."""
    if in_sandbox():
        # The sandbox accepts any string. Demanding a token here would invent a
        # requirement the API doesn't have, and that requirement loses exactly
        # the person who has no way to get one yet.
        return Secret("sandbox")
    path = (os.environ.get("OURA_PAT_FILE") or "").strip()
    if path:
        try:
            t = open(os.path.expanduser(path), encoding="utf-8").read().strip()
        except OSError as e:
            raise OuraError(f"could not read OURA_PAT_FILE: {e.strerror}") from None
        if not t:
            raise OuraError(f"OURA_PAT_FILE points at an empty file: {path}")
        return Secret(t)
    t = (os.environ.get("OURA_PAT") or "").strip()
    if t:
        return Secret(t)
    return _oauth_token()


def _oauth_token() -> Secret:
    """The OAuth2 access token, refreshing it when needed.

    Imported inside the function because `credentials` imports from this module.
    The alternative was splitting `Secret` and `OuraError` into a third file,
    which is more ceremony than a deferred import deserves.
    """
    from .credentials import load, refresh

    cred = load()
    if cred is None:
        # THE MESSAGE MATTERS. It used to point at the personal-tokens page, and
        # since December 2025 that page won't issue any: whoever landed there got
        # stuck without knowing why. Now the first option is the one that works,
        # and the sandbox comes before everything because it lets you see the
        # server run without obtaining any credential at all.
        raise OuraError(
            "no credentials. Three paths, from least to most paperwork:\n"
            "  1. OURA_SANDBOX=1 — sample data, no signup of any kind\n"
            "  2. oura-mcp --authorize — OAuth2, once, in the browser\n"
            "  3. OURA_PAT / OURA_PAT_FILE — only if you already had a personal "
            "token: Oura stopped issuing them in December 2025"
        )
    if not cred.expired():
        return cred.access
    from .authorize import app_credentials
    cid, csec = app_credentials()
    return refresh(cred, cid, csec).access


def _requested_wait(e: urllib.error.HTTPError, attempt: int) -> float:
    """How long to wait after a 429: whatever `Retry-After` says, or backoff.

    `Retry-After` allows two forms — seconds, or an HTTP date — and Oura doesn't
    document which it sends. Both are accepted, and if neither arrives the
    fallback is exponential backoff, the only reasonable thing when the server
    says nothing. Capped at `MAX_WAIT`: a header asking for half an hour can't
    leave a conversation hanging.
    """
    header = (e.headers.get("Retry-After") or "").strip() if e.headers else ""
    if header:
        try:
            return min(float(header), MAX_WAIT)
        except ValueError:
            pass
        try:
            when = email.utils.parsedate_to_datetime(header)
            remaining = (when - datetime.datetime.now(when.tzinfo)).total_seconds()
            return min(max(remaining, 0.0), MAX_WAIT)
        except (TypeError, ValueError):
            pass
    return min(2.0 ** attempt, MAX_WAIT)


def _detail_of(e: urllib.error.HTTPError) -> str:
    """The readable part of Oura's error body, or the raw one, trimmed.

    Oura answers `detail` in two different shapes and neither reads well raw.
    One is a string; the other is pydantic's validation-error array, whose JSON
    runs past 200 characters before reaching the only thing that matters — which
    field and why — so trimming it left the reader with
    `{"detail":[{"type":"datetime_from_date_parsing","loc":["query","star` and
    nothing else.
    """
    try:
        body = json.loads(e.read().decode("utf-8", "replace"))
    except Exception:
        return ""
    d = body.get("detail") if isinstance(body, dict) else None
    if isinstance(d, str):
        return ": " + d[:200]
    if isinstance(d, list):
        parts = []
        for item in d[:2]:              # two is plenty: the rest repeats the field
            if not isinstance(item, dict):
                continue
            field = ".".join(str(x) for x in (item.get("loc") or [])[1:2]) or "?"
            msg = item.get("msg") or ""
            received = item.get("input")
            parts.append(f"{field}: {msg}"
                         + (f" (received: {received!r})" if received is not None else ""))
        if parts:
            return ": " + "; ".join(parts)[:200]
    return ": " + json.dumps(body, ensure_ascii=False)[:200]


def _request(url: str, token: Secret, retries: int = RETRIES_429) -> dict:
    """One request to Oura, with a bounded retry for the 429 only.

    ONLY the 429 is retried. A 401 doesn't improve by waiting and neither does a
    422: all retrying them achieves is taking three times as long to deliver the
    same bad news.

    Oura sends NO rate-limit headers on successful responses — verified
    2026-08-09: no `X-RateLimit-Remaining` or equivalent — so a client can't know
    how close it is to the ceiling. It only finds out once it's been refused. For
    a query that can chain 50 pages, giving up on the first 429 throws away
    everything already fetched.
    """
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token.reveal()}",
                      "Accept": "application/json"}
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                time.sleep(_requested_wait(e, attempt))
                continue
            detail = _detail_of(e)
            if e.code == 401:
                raise OuraError("Oura rejected the token (401). Did it expire?") from None
            if e.code == 429:
                raise OuraError(
                    f"Oura is rate limiting (429) and kept doing so after "
                    f"{retries} retries. Wait a bit and shorten the range."
                ) from None
            raise OuraError(f"Oura responded {e.code}{detail}") from None
        except urllib.error.URLError as e:
            raise OuraError(f"could not reach Oura: {e.reason}") from None
    raise OuraError("Oura did not respond")   # unreachable; the loop always exits


def day_of(record: dict) -> str | None:
    """The day a record belongs to, or None if it can't be determined.

    None means "I don't know", and whoever filters must KEEP IT. Discarding what
    you don't understand is the fastest way to under-deliver.
    """
    if not isinstance(record, dict):
        return None
    for k in _DAY_KEYS:
        v = record.get(k)
        if isinstance(v, str) and v:
            return v[:10]
    for k in _TIME_KEYS:
        v = record.get(k)
        if isinstance(v, str) and len(v) >= 10:
            return v[:10]
    return None


def _shift_days(date: str, days: int) -> str:
    """`YYYY-MM-DD` ± days. If it doesn't parse, it's returned untouched.

    A failure to parse isn't worth raising here: a malformed date is rejected by
    Oura with a 422 that explains what it expected, and that message is more
    useful than anything we could invent.
    """
    try:
        return (datetime.date.fromisoformat(date[:10])
                + datetime.timedelta(days=days)).isoformat()
    except ValueError:
        return date


def to_csv(data: list) -> tuple[str, list[str], bool]:
    """The records as CSV. Returns (text, columns, whether they're uneven).

    A month of `heartrate` is ~37,000 records; in JSON that repeats the same four
    keys 37,000 times. CSV writes them once.

    THE HEADER COMES FROM THE UNION OF ALL KEYS, not from the first record.
    Taking it from the first is the easiest way to lose data here: one record
    with an extra field is enough for that field to vanish without a trace, which
    is exactly the kind of failure this package exists not to commit.

    Nested values — `contributors` and friends — are written as JSON in their
    cell. Flattening would invent columns Oura doesn't have; omitting would lose
    data.
    """
    rows = [r for r in data if isinstance(r, dict)]
    keys = set()
    for r in rows:
        keys |= set(r)
    # The date first: it's the column a model joins against another source with,
    # and hunting for it mid-table is friction for no reason.
    front = [k for k in ("day", "timestamp", "start_day", "id") if k in keys]
    columns = front + sorted(keys - set(front))
    uneven = any(set(r) != keys for r in rows)

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    for r in rows:
        writer.writerow([_cell(r.get(c)) for c in columns])
    return buf.getvalue(), columns, uneven


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return str(v)


def _why_empty(collection: str, start: str | None, end: str | None) -> dict:
    """What is known when the query comes back with nothing.

    `n: 0` is the most common answer to the most common questions — "how did I
    sleep last night?", "am I recovered?" — and it doesn't distinguish between
    four things that lead to opposite conclusions:

        you weren't wearing the ring   ·  the ring hasn't synced yet
        you asked for a future date    ·  your token lacks that scope

    A model receiving `{"n": 0}` will answer "you didn't sleep" with complete
    confidence, and may be wrong. This does NOT guess which one it is: it lists
    what can be checked without going to the network, and leaves the rest open.
    """
    from .collections import SCOPE_OF

    today = datetime.date.today().isoformat()
    reasons = []

    if start and end:
        if start[:10] > today:
            reasons.append("the requested range is in the future")
        elif end[:10] >= today:
            reasons.append(
                "the range reaches today, and Oura's data only appears once the "
                "ring syncs with the app; the current day is usually missing or "
                "incomplete")

    scope = SCOPE_OF.get(collection)
    if scope and not (in_sandbox() or os.environ.get("OURA_PAT")
                      or os.environ.get("OURA_PAT_FILE")):
        try:
            from .credentials import load
            cred = load()
        except OuraError:
            cred = None
        if cred and scope not in cred.scopes:
            reasons.append(
                f"this collection needs the `{scope}` scope and your credentials "
                f"don't have it: run `oura-mcp --authorize` again and grant it")

    return {
        "no_data": "the query succeeded; Oura has no records in that range",
        "what_we_know": reasons or ["nothing further to report without hitting the network"],
        "do_not_confuse": ("«no data» is not the same as «you didn't sleep» or "
                           "«you didn't recover». To find out whether the ring "
                           "has data nearby, ask for a wider range."),
    }


def _size_warning(data: list, fields: list[str] | None) -> dict | None:
    """If the response is enormous, say so and point at the field inflating it.

    Measured 2026-08-09: 30 days of `daily_activity` is **252,000 characters**,
    and 92% of each record is `met` — a per-minute MET series. Asking for three
    columns brings that down to 5,000: 99% less.

    A server handing over a quarter of a million characters without commenting is
    spending the asker's context on data they probably didn't want. Nothing is
    trimmed on our own initiative — that would be under-delivering, exactly what
    this package exists not to do — everything is delivered, and what's heavy is
    named along with how to ask for less.
    """
    if fields or len(data) < 2:
        return None                     # they already chose columns, or there's no volume
    total = sum(len(json.dumps(r, ensure_ascii=False)) for r in data
                if isinstance(r, dict))
    if total < SIZE_WARNING:
        return None
    weights: dict[str, int] = {}
    for r in data:
        if isinstance(r, dict):
            for k, v in r.items():
                weights[k] = weights.get(k, 0) + len(json.dumps(v, ensure_ascii=False))
    heaviest, weight = max(weights.items(), key=lambda kv: kv[1], default=("", 0))
    pct = round(weight * 100 / total) if total else 0
    return {
        "characters": total,
        "heaviest_field": heaviest,
        "percentage": pct,
        "suggestion": (f"`{heaviest}` takes up {pct}% of this response. If you "
                       f"don't need it, ask only for the columns you use with "
                       f"`fields`, or shorten the range."),
    }


def _ignored_fields(fields: list[str] | None, data: list) -> list[str]:
    """The requested fields that showed up in no record.

    Oura does NOT complain about a field name that doesn't exist. Measured
    2026-08-09: `fields=made_up` returns the COMPLETE record — the projection
    never happens — and `fields=score,made_up` applies the good one and drops the
    bad one without a word. In both cases the asker believes they filtered and
    didn't.

    This warns rather than fails: a field can be legitimately absent because
    there's no data for it. That's why the name is "didn't appear", not
    "doesn't exist".
    """
    if not fields or not data:
        return []
    present = set()
    for r in data:
        if isinstance(r, dict):
            present |= set(r)
    return sorted(f for f in fields if f not in present)


def _trim(data: list, start: str | None, end: str | None,
          s: str) -> tuple[list, int]:
    """Keep only records whose `day` falls in [start, end].

    Returns (data, how many were discarded). Applies to `date_range` only: it's
    the trim of the two extra days that were requested on purpose.

    A record whose day CANNOT be determined is kept. This filter exists to
    correct a deliberate widening, not to decide what counts as valid data —
    discarding what you don't understand is the fastest way to under-deliver,
    which is precisely what this package exists not to do.
    """
    if s != "date_range" or not (start and end):
        return data, 0
    floor, ceiling = start[:10], end[:10]
    inside = [r for r in data
              if (d := day_of(r)) is None or floor <= d <= ceiling]
    return inside, len(data) - len(inside)


def fetch(collection: str, start: str | None = None, end: str | None = None,
          fields: list[str] | None = None, latest: bool = False,
          format: str = "json", page_limit: int = PAGE_LIMIT) -> dict:
    """Fetch a COMPLETE collection over the requested range.

    Returns `{"collection", "n", "pages", "data", …}` plus whichever warnings
    apply. An incomplete result that doesn't declare itself incomplete is the
    worst of both worlds: it looks exactly like a complete one.
    """
    s = shape(collection)
    token = _token()
    params: dict[str, str] = {}

    if in_sandbox() and collection in WITHOUT_SANDBOX:
        # Caught BEFORE the request. The sandbox answers a bare 404, and a
        # "404: Not Found" tells someone who just installed that the server is
        # broken — when what's actually happening is that Oura doesn't publish
        # fake data for the one collection carrying email, age, weight and
        # height.
        raise OuraError(
            f"`{collection}` does not exist in Oura's sandbox: it's the only one "
            f"of the 19 that isn't served there, because it's the one returning "
            f"personal data. Everything else works here. To see your real one, "
            f"drop OURA_SANDBOX and run `oura-mcp --authorize`."
        )

    if latest:
        # Oura does NOT complain when `latest` is sent to a collection that
        # doesn't support it: it returns the entire collection. Asking for the
        # latest record and receiving ten while believing it's one is worse than
        # an error.
        if collection not in WITH_LATEST:
            raise OuraError(
                f"`latest` is only honored by Oura on {', '.join(sorted(WITH_LATEST))}; "
                f"on {collection} it's ignored and the whole collection comes back"
            )
        params["latest"] = "true"
    if fields:
        params["fields"] = ",".join(fields)

    if s in WITH_DATE and not latest:
        if not start or not end:
            raise OuraError(f"{collection} needs start and end")
        if start > end:
            # Caught HERE and not at Oura because the EXTRA_DAYS margin changes
            # the dates: Oura would return a 400 quoting two dates the asker
            # never wrote, and diagnosing that costs more than the error itself.
            raise OuraError(
                f"the range runs backwards: start ({start}) is after end ({end})"
            )
        key = "date" if s == "date_range" else "datetime"
        # TWO EXTRA DAYS ARE REQUESTED ON EACH SIDE AND TRIMMED HERE. Two
        # distinct failures force it, both measured against the real API on
        # 2026-08-09 and both silent:
        #
        # 1. `end_date` is INCONSISTENT ACROSS COLLECTIONS. Asking for [d..d]:
        #      inclusive   daily_sleep, daily_readiness, daily_stress,
        #                  daily_spo2, daily_resilience,
        #                  daily_cardiovascular_age, sleep_time
        #      EXCLUSIVE   daily_activity, sleep, workout  <- they lose the day
        #
        # 2. `workout` (and anything carrying a time) is FILTERED BY UTC DATE
        #    but reports `day` in local time. At -06:00, an evening workout
        #    lands on the next UTC day: asking for [16..18] returned records
        #    from the 15th and 16th.
        #
        # A per-collection table doesn't work: five collections had no data to
        # measure them with, and a table Oura changes fails silently again.
        # Widening and trimming is correct in all four cases — inclusive,
        # exclusive, and skewed in either direction — and stays correct when
        # Oura changes it. The cost is two days of data thrown away.
        if s == "date_range":
            params["start_date"] = _shift_days(start, -EXTRA_DAYS)
            params["end_date"] = _shift_days(end, +EXTRA_DAYS)
        else:
            params[f"start_{key}"] = start
            params[f"end_{key}"] = end

    root = base()
    data, pages, next_token = [], 0, None
    truncated, cursor, cycle = None, None, None
    seen: set[str] = set()
    while True:
        q = dict(params)
        if next_token:
            q["next_token"] = next_token
        url = f"{root}/{collection}" + (f"?{urllib.parse.urlencode(q)}" if q else "")
        body = _request(url, token)
        pages += 1

        # `personal_info` and `ring_configuration` don't come wrapped in `data`:
        # the ENTIRE body is the record. That's told apart by the ABSENCE of the
        # key, not by it failing to be a list. The difference matters: if `data`
        # arrives and isn't a list, something changed in the API, and wrapping
        # the whole envelope would turn that into "one record" shaped like
        # `{"data": …}` that looks legitimate. Staying quiet about it would be
        # the usual failure, committed by us.
        if "data" in body:
            raw = body["data"]
            if isinstance(raw, list):
                chunk = raw
            else:
                raise OuraError(
                    f"Oura returned `data` as {type(raw).__name__} rather than a "
                    f"list on {collection}. The response shape changed; no "
                    f"interpretation is being invented."
                )
        else:
            chunk = [body] if body else []
        data.extend(chunk)

        next_token = body.get("next_token")
        if not next_token:
            break
        if next_token in seen:
            # A REPEATED `next_token` IS A CYCLE. Without this the client made 50
            # identical requests, returned 50 copies of the same record, and the
            # warning said "shorten the range" — useless advice, because
            # shortening doesn't stop the API from repeating itself. And it burned
            # 49 requests against a rate limit Oura announces in no header.
            #
            # This isn't truncation and mustn't be called that: it's the API
            # misbehaving. Say so plainly, with whatever was fetched.
            cycle = ("Oura repeated the same `next_token`: that's a cycle, and it "
                     "stopped rather than ask for the same thing forever. What "
                     "follows reaches as far as it got and may be incomplete.")
            break
        seen.add(next_token)
        if pages >= page_limit:
            # ONE EXIT ONLY. With two, the truncated response left without going
            # through the formatting or the warnings — and it's precisely the
            # response that most needs everything it says to be believed.
            truncated = (f"stopped at {page_limit} pages and Oura was offering "
                         f"more; shorten the range or continue from `continue_from`")
            cursor = next_token
            break

    data, discarded = _trim(data, start, end, s)
    out = {"collection": collection, "n": len(data), "pages": pages, "data": data}
    if truncated:
        out["truncated"] = truncated
        out["continue_from"] = cursor
    if cycle:
        out["pagination_cycle"] = cycle
    if format == "csv":
        text, columns, uneven = to_csv(data)
        out["data"] = text
        out["format"] = "csv"
        out["columns"] = columns
        if uneven:
            # An empty cell can mean "the field wasn't there" or "it came back
            # null". With records of differing shape that difference matters, and
            # hiding it would hand over a table pretending to more regularity
            # than it has.
            out["uneven_columns"] = (
                "not every record carries the same keys; an empty cell may be an "
                "absent field or a null value"
            )
    if (ignored := _ignored_fields(fields, data)):
        out["ignored_fields"] = ignored
    if (warning := _size_warning(data, fields)):
        out["large_response"] = warning
    if discarded:
        # The extra days were requested on purpose; this is what got dropped.
        # Said out loud rather than swallowed: whoever reads the response has to
        # be able to tell "there is no data" from "we removed it".
        out["discarded_out_of_range"] = discarded
    if not data:
        out["empty"] = _why_empty(collection, start, end)
    if in_sandbox():
        # EVERY sandbox response says so. `oura_check` said it and the queries
        # did not, so someone asking "how did I sleep?" got a score of 73 out of
        # Oura's fake data with nothing marking it — which is this package's own
        # thesis committed by us, in the default configuration. A model reading
        # this key cannot report synthetic numbers as the person's own.
        out["synthetic"] = SYNTHETIC
    return out
