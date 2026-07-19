"""Edge-case coverage: triage scoring, phase boundaries, route orientation,
caching, limiter eviction, log bounding, unicode sanitisation.

These complement the happy-path tests with boundary and adversarial inputs.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.ai import nlu
from app.security import SlidingWindowRateLimiter, sanitize_text
from app.services import crowd, knowledge
from app.services.assistant import Assistant
from app.services.incidents import IncidentLog, priority_label, triage_score

from .conftest import make_settings

FINAL_KICKOFF = datetime(2026, 7, 19, 19, 0, tzinfo=timezone.utc)  # MetLife final


@pytest.fixture(scope="module")
def assistant() -> Assistant:
    return Assistant(make_settings())


# --------------------------- incident triage ----------------------------


def test_triage_crowd_escalates_sensitive_category():
    # security base is 4; high/critical crowd bumps sensitive categories by 1.
    assert triage_score("security", None, "low") == 4
    assert triage_score("security", None, "critical") == 5


def test_triage_crowd_ignored_for_non_sensitive_category():
    assert triage_score("lost_item", None, "critical") == 1


def test_triage_is_capped_at_five():
    assert triage_score("medical", 5, "critical") == 5  # 5 + 1, capped


def test_triage_severity_hint_raises_floor():
    assert triage_score("cleaning", 4, "low") == 4  # base 1, hint 4 wins


def test_priority_label_boundaries():
    assert priority_label(5) == "critical"
    assert priority_label(4) == "high"
    assert priority_label(3) == "medium"
    assert priority_label(2) == "low"
    assert priority_label(1) == "low"


# --------------------------- match phase edges ---------------------------


def test_phase_at_exact_kickoff_is_in_match():
    assert knowledge.match_phase("metlife", FINAL_KICKOFF) == "in_match"


def test_phase_four_hours_before_is_ingress():
    assert knowledge.match_phase("metlife", FINAL_KICKOFF - timedelta(hours=4)) == "ingress"


def test_phase_just_before_ingress_window_is_quiet():
    assert knowledge.match_phase("metlife", FINAL_KICKOFF - timedelta(hours=4, minutes=1)) == "quiet"


def test_phase_after_egress_window_is_quiet():
    assert knowledge.match_phase("metlife", FINAL_KICKOFF + timedelta(hours=5)) == "quiet"


def test_next_match_is_none_after_all_fixtures():
    assert knowledge.next_match("azteca", datetime(2027, 1, 1, tzinfo=timezone.utc)) is None


# ------------------------------ nlu edges --------------------------------


def test_language_detection_from_punctuation_and_accents():
    assert nlu.detect_language("¿?") == "es"   # inverted question mark
    assert nlu.detect_language("ça") == "fr"    # cedilla


def test_seat_does_not_trigger_food_facility():
    assert nlu.facility_type_from_text("where is my seat number") is None


# --------------------- route orientation (to / from) ---------------------


def test_route_orientation_handles_reversed_cue(assistant):
    # "to Gate D" is the destination even though it appears before the origin.
    res = assistant.answer(
        message="How do I get to Gate D from the parking?",
        venue_id="azteca",
        at=FINAL_KICKOFF,
    )
    route = res["data"]["route"]
    assert route["origin"] == "parking"
    assert route["destination"] == "gate_d"


# ------------------------- caching / determinism -------------------------


def test_snapshot_within_bucket_is_cached_identity():
    a = crowd.snapshot("azteca", FINAL_KICKOFF)
    b = crowd.snapshot("azteca", FINAL_KICKOFF)
    assert a is b  # served from the per-bucket cache


# --------------------------- rate limiter --------------------------------


def test_rate_limiter_evicts_oldest_key_under_pressure():
    limiter = SlidingWindowRateLimiter(limit=1, max_keys=2)
    assert limiter.allow("k1")
    assert limiter.allow("k2")
    assert limiter.allow("k3")  # forces eviction of a stale key, still allowed
    assert len(limiter._hits) <= 2  # never exceeds the memory bound


# ---------------------------- incident log -------------------------------


def test_incident_log_is_bounded():
    log = IncidentLog(max_items=3)
    for i in range(5):
        log.create("azteca", "gate_a", "Gate A", "cleaning", f"spill {i}", None, "low")
    assert len(log.list("azteca")) == 3


def test_incident_log_filters_by_venue():
    log = IncidentLog()
    log.create("azteca", "gate_a", "Gate A", "medical", "x", None, "low")
    log.create("metlife", "gate_b", "Gate B", "medical", "y", None, "low")
    assert all(i.venue_id == "azteca" for i in log.list("azteca"))
    assert len(log.list()) == 2  # no filter -> all venues


# --------------------------- sanitisation --------------------------------


def test_sanitize_preserves_multilingual_characters():
    text = "¿Dónde está la salida? Où se trouve la sortie? ça va"
    assert sanitize_text(text) == text
