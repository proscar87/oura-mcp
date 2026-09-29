"""`tools/check_drift.py`, the auth half — run offline against specs written here.

WHY THE AUTH SURFACE GOT A CHECK. The drift job watched the 19 collections and
nothing else, and the one break that reached users in September 2026 was not a
collection: Oura renamed `spo2Daily` to `spo2`, added `heart_health`, and began
granting scopes as `extapi:daily`. The last one reached this server through a
competitor's issue tracker, not through anything here. These tests pin what the
weekly job now compares: the scopes the spec offers against the ones requested,
and — the day Oura starts declaring them — each collection's scope against
`SCOPE_OF`.
"""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("check_drift", ROOT / "tools" / "check_drift.py")
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)


def _spec_with(scopes, per_path=None):
    paths = {}
    for name, needs in (per_path or {}).items():
        op = {"security": [{"OAuth2": needs}]} if needs is not None else {}
        paths[f"/v2/usercollection/{name}"] = {"get": op}
    return {"paths": paths, "components": {"securitySchemes": {
        "OAuth2": {"type": "oauth2", "flows": {"authorizationCode": {
            "scopes": {s: "" for s in scopes}}}}}}}


SPEC_1_40 = ["daily", "email", "heart_health", "heartrate", "personal", "session",
             "spo2", "tag", "workout"]


def test_the_current_spec_passes():
    lines, bad = D.compare_scopes(_spec_with(SPEC_1_40))
    assert not bad, lines


def test_a_renamed_scope_fails():
    """`spo2Daily` → `spo2` was exactly this, the other way round."""
    renamed = [s for s in SPEC_1_40 if s != "spo2"] + ["spo2_daily"]
    lines, bad = D.compare_scopes(_spec_with(renamed))
    assert bad
    text = "\n".join(lines)
    assert "spo2_daily" in text and "spo2" in text


def test_a_new_scope_fails_until_someone_decides():
    lines, bad = D.compare_scopes(_spec_with(SPEC_1_40 + ["stress"]))
    assert bad
    assert "stress" in "\n".join(lines)


def test_heart_health_is_known_and_not_requested_on_purpose():
    lines, bad = D.compare_scopes(_spec_with(SPEC_1_40))
    assert any("heart_health" in l for l in lines)


def test_per_collection_scopes_are_checked_against_scope_of_once_declared():
    """Today the spec declares none, which is why `heart_health` and `stress`
    are open questions. The day it does, this answers them."""
    lines, bad = D.compare_scopes(_spec_with(SPEC_1_40, per_path={
        "daily_cardiovascular_age": ["heart_health"], "daily_sleep": ["daily"]}))
    assert bad
    assert "daily_cardiovascular_age" in "\n".join(lines)

    lines, bad = D.compare_scopes(_spec_with(SPEC_1_40, per_path={"daily_sleep": ["daily"]}))
    assert not bad, lines


def test_no_per_collection_scopes_is_said_not_assumed():
    lines, _ = D.compare_scopes(_spec_with(SPEC_1_40, per_path={"daily_sleep": None}))
    assert any("declares no" in l for l in lines)


def test_every_spec_scope_survives_the_extapi_prefix():
    lines, bad = D.compare_scopes(_spec_with(SPEC_1_40))
    assert not bad
    assert any("extapi:" in l for l in lines)


def test_a_spec_without_an_oauth_block_is_unreadable_not_empty():
    lines, bad = D.compare_scopes({"paths": {}, "components": {}})
    assert bad is None


# ── The fingerprint: any change, not only the ones we thought to watch ─────
def test_the_fingerprint_sees_a_new_field_a_new_enum_value_and_a_new_parameter():
    """Oura deletes superseded specs — 1.37 and 1.40 both answer 404 now — so a
    change can only be diffed against a copy kept here. The workout `source`
    enum gained two values between 1.37 and 1.40 and nothing noticed."""
    old = {"paths": {"/v2/usercollection/workout": {"get": {"parameters": [
               {"name": "start_date"}]}}},
           "components": {"schemas": {
               "PublicWorkout": {"properties": {"id": {}, "day": {}}},
               "WorkoutSource": {"enum": ["manual", "autodetected"]}}}}
    new = {"paths": {"/v2/usercollection/workout": {"get": {"parameters": [
               {"name": "start_date"}, {"name": "fields"}]}}},
           "components": {"schemas": {
               "PublicWorkout": {"properties": {"id": {}, "day": {}, "strain": {}}},
               "WorkoutSource": {"enum": ["manual", "autodetected", "live_oura_heart_rate"]}}}}
    lines = D.fingerprint_changes(D.fingerprint(old), D.fingerprint(new))
    text = "\n".join(lines)
    assert "fields" in text
    assert "strain" in text
    assert "live_oura_heart_rate" in text


def test_an_unchanged_spec_has_no_changes():
    spec = {"paths": {}, "components": {"schemas": {"A": {"properties": {"x": {}}}}}}
    assert D.fingerprint_changes(D.fingerprint(spec), D.fingerprint(spec)) == []


def test_the_committed_fingerprint_is_readable_and_names_its_version():
    import json
    fp = json.loads((ROOT / "tools" / "spec_fingerprint.json").read_text(encoding="utf-8"))
    assert fp["version"].startswith("openapi-")
    assert "/v2/usercollection/workout" in " ".join(fp["paths"])
