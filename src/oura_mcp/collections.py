"""The 19 collections of the Oura v2 API, and nothing else.

All the complexity of talking to Oura lives in these tables. The rest — the
client, the MCP server — is presentation. That's why this is its own file: if
Oura adds a collection, you touch this and nothing else.

FOUR PARAMETER SHAPES, not nineteen:

    date_range      start_date / end_date          (most of them)
    datetime_range  start_datetime / end_datetime  (heartrate, battery)
    single          no parameters                  (personal_info)
    token_only      no parameters, no date         (ring_configuration)
"""

from __future__ import annotations

BASE = "https://api.ouraring.com/v2/usercollection"

# {name: (shape, what it carries)}
COLLECTIONS: dict[str, tuple[str, str]] = {
    # Daily summaries: what gets queried day to day.
    "daily_sleep":              ("date_range", "sleep score and its contributors"),
    "daily_readiness":          ("date_range", "readiness score and its contributors"),
    "daily_activity":           ("date_range", "steps, calories, time by intensity"),
    "daily_stress":             ("date_range", "minutes of stress and recovery"),
    "daily_spo2":               ("date_range", "average overnight oxygen saturation"),
    "daily_resilience":         ("date_range", "resilience (limited…exceptional)"),
    "daily_cardiovascular_age": ("date_range", "estimated cardiovascular age"),
    "vO2_max":                  ("date_range", "estimated VO2 max"),

    # The detail the scores hide.
    "sleep":        ("date_range", "sleep sessions: stages, HRV, temperature, latency"),
    "sleep_time":   ("date_range", "recommended sleep window"),
    "workout":      ("date_range", "workouts with type, duration and intensity"),
    "session":      ("date_range", "breathing, meditation and nap sessions"),
    "rest_mode_period": ("date_range", "rest mode periods"),
    "tag":          ("date_range", "tags (deprecated: Oura recommends enhanced_tag)"),
    "enhanced_tag": ("date_range", "tags with start and end times"),

    # High resolution. The only ones that FORCE pagination.
    "heartrate":          ("datetime_range", "heart rate every 5 min"),
    "ring_battery_level": ("datetime_range", "ring battery"),

    # No range.
    "personal_info":      ("single", "age, weight, height, biological sex"),
    "ring_configuration": ("token_only", "ring model, size and color"),
}

WITH_DATE = {"date_range", "datetime_range"}

# The ones Oura's sandbox does NOT serve. It's exactly one, and that makes
# sense: it's the only collection returning email, age, weight and height. It
# lives here rather than in the drift script because the client needs it too —
# without this, asking for the profile in sandbox mode returned a bare
# `404: Not Found`, and anyone who had just installed would conclude the server
# was broken.
WITHOUT_SANDBOX = {"personal_info"}

# Which OAuth scope each collection needs. It serves exactly one purpose, and
# it matters: when a query comes back EMPTY, telling "there is no data" apart
# from "you didn't grant that permission". The two look identical — n=0 — and
# lead to opposite conclusions.
SCOPE_OF = {
    "daily_sleep": "daily", "daily_readiness": "daily", "daily_activity": "daily",
    "daily_stress": "daily", "daily_resilience": "daily",
    "daily_cardiovascular_age": "daily", "vO2_max": "daily",
    "sleep": "daily", "sleep_time": "daily", "rest_mode_period": "daily",
    "ring_battery_level": "daily", "ring_configuration": "daily",
    "daily_spo2": "spo2",
    "heartrate": "heartrate",
    "workout": "workout",
    "session": "session",
    "tag": "tag", "enhanced_tag": "tag",
    "personal_info": "personal",
}

# The only two that honor `latest=true`. Measured against the API on
# 2026-08-09: on the others Oura does NOT return an error, it returns the entire
# collection. Asking for the latest record and getting ten, with no warning, is
# the same family of failure as not paginating — which is why it's rejected here
# before going anywhere near the network.
WITH_LATEST = {"heartrate", "ring_battery_level"}


def shape(collection: str) -> str:
    """The collection's parameter shape. KeyError if it doesn't exist — deliberately.

    A made-up name has to blow up HERE and not turn into a request to a URL that
    doesn't exist, whose 404 then has to be interpreted.
    """
    return COLLECTIONS[collection][0]


def describe() -> str:
    """The 19 collections with their descriptions, for the tool prompt."""
    return "\n".join(f"  {n:<24} {d}" for n, (_s, d) in COLLECTIONS.items())
