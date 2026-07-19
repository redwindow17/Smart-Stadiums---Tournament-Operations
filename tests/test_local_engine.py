"""Offline-engine renderers, the recommendations rules engine, and config
fallbacks - the branches the happy-path suites don't reach."""
from __future__ import annotations

import sys
from datetime import timedelta

import pytest

from app.ai.local_engine import LocalEngine
from app.config import load_settings
from app.services import crowd, knowledge, navigation
from app.services.assistant import Assistant

from .conftest import INGRESS_AT_METLIFE, make_settings

FINAL_KICKOFF = INGRESS_AT_METLIFE + timedelta(hours=3)  # 19:00Z


@pytest.fixture(scope="module")
def assistant() -> Assistant:
    return Assistant(make_settings())


engine = LocalEngine()

# --------------------------- renderer branches ---------------------------


def test_accessibility_reply_lists_features(assistant):
    res = assistant.answer(
        message="Is the stadium wheelchair friendly?", venue_id="azteca", at=INGRESS_AT_METLIFE
    )
    assert res["intent"] == "accessibility"
    assert "Accessibility at" in res["reply"]
    assert "elevator" in res["reply"].lower() or "wheelchair" in res["reply"].lower()


def test_sustainability_reply_lists_tips(assistant):
    res = assistant.answer(
        message="Where can I recycle this bottle?", venue_id="bcplace", at=INGRESS_AT_METLIFE
    )
    assert res["intent"] == "sustainability"
    assert "Sustainability at" in res["reply"]
    assert "-" in res["reply"]  # bullet list of tips


def test_first_aid_reply_includes_emergency_note(assistant):
    res = assistant.answer(message="I need first aid, I'm hurt", venue_id="azteca", at=INGRESS_AT_METLIFE)
    assert res["intent"] == "facility"
    assert "emergency" in res["reply"].lower()


def test_navigation_without_destination_asks_for_one(assistant):
    res = assistant.answer(message="How do I get there?", venue_id="azteca", at=INGRESS_AT_METLIFE)
    assert res["intent"] == "navigation"
    assert "Gate C" in res["reply"]  # the example in the re-prompt


def test_navigation_reply_includes_crowd_hint_when_gates_busy(assistant):
    # At this fixed bucket MetLife's busiest gate sits at 84% (deterministic).
    res = assistant.answer(message="How do I get to Gate B?", venue_id="metlife", at=INGRESS_AT_METLIFE)
    assert "busiest" in res["reply"].lower()


def test_live_match_reply(assistant):
    res = assistant.answer(
        message="Who plays right now?",
        venue_id="metlife",
        at=FINAL_KICKOFF + timedelta(minutes=30),
    )
    assert res["data"]["match"]["status"] == "live"
    assert "right now" in res["reply"].lower()


def test_unknown_intent_falls_back_to_general_template():
    reply = engine.generate("?", {"intent": "nonexistent", "venue": {"name": "X"}, "language": "en"})
    assert "I can help" in reply


def test_route_none_template_when_no_route_found():
    ctx = {"intent": "navigation", "language": "en", "route_requested": True, "route": None, "accessible": True}
    assert "step-free" in engine.generate("?", ctx)


def test_facility_none_template():
    ctx = {"intent": "facility", "language": "en", "facilities": [], "venue": {"name": "X"}}
    assert "Info Desk" in engine.generate("?", ctx)


def test_crowd_renderer_without_data_degrades_to_general():
    ctx = {"intent": "crowd", "language": "en", "venue": {"name": "X"}}
    assert "I can help" in engine.generate("?", ctx)


def test_unknown_language_falls_back_to_english():
    ctx = {"intent": "greeting", "language": "de", "venue": {"name": "X"}}
    assert "StadiumIQ" in engine.generate("hallo", ctx)


# --------------------- recommendations rules engine ----------------------


def _zone(zone_id: str, kind: str, density: float, trend: str = "steady") -> dict:
    return {
        "zone_id": zone_id,
        "zone_name": zone_id.replace("_", " ").title(),
        "kind": kind,
        "density": density,
        "level": crowd.level_for(density),
        "trend": trend,
    }


def test_rules_engine_on_a_critical_snapshot():
    """Feed the rules engine a handcrafted worst-case snapshot (the hash
    simulation rarely produces one) and verify every escalation fires."""
    snap = {
        "phase": "egress",
        "zones": [
            _zone("gate_a", "gate", 0.95, trend="rising"),   # critical -> P1 redirect
            _zone("gate_b", "gate", 0.30),                    # the relief gate
            _zone("gate_c", "gate", 0.70),                    # high -> P2 lanes
            _zone("concourse_x", "concourse", 0.85),          # critical -> P1 one-way flow
        ],
    }
    actions = [r["action"] for r in crowd.recommendations(snap)]
    joined = " | ".join(actions)
    assert "Redirect arriving fans from Gate A to Gate B" in joined
    assert "screening lanes" in joined
    assert "one-way pedestrian flow" in joined
    assert "hold-and-release" in joined  # egress + avg gate density > 60%
    priorities = [r["priority"] for r in crowd.recommendations(snap)]
    assert priorities == sorted(priorities)  # P1 actions surface first


def test_level_for_extreme_density_is_critical():
    assert crowd.level_for(2.5) == "critical"


def test_snapshot_cache_stays_bounded():
    for minutes in range(0, 400, 10):  # 40 distinct buckets > cache max of 32
        crowd.snapshot("azteca", INGRESS_AT_METLIFE + timedelta(minutes=minutes))
    assert len(crowd._cache) <= crowd._CACHE_MAX


# --------------------------- knowledge edges -----------------------------


def test_phase_egress_window():
    assert knowledge.match_phase("metlife", FINAL_KICKOFF + timedelta(hours=3)) == "egress"


# --------------------------- navigation guards ---------------------------

_DISCONNECTED_VENUE = {
    "zones": [
        {"id": "a", "name": "A", "kind": "gate"},
        {"id": "b", "name": "B", "kind": "gate"},  # no edge to A
    ],
    "edges": [],
    "facilities": [{"type": "restroom", "name": "R", "zone": "b"}],
}


def test_route_is_none_when_zones_disconnected():
    assert navigation.shortest_route(_DISCONNECTED_VENUE, "a", "b") is None


def test_nearest_facilities_from_unknown_origin_is_empty():
    assert navigation.nearest_facilities(_DISCONNECTED_VENUE, "nope", "restroom") == []


def test_unreachable_facility_is_skipped():
    assert navigation.nearest_facilities(_DISCONNECTED_VENUE, "a", "restroom") == []


# ----------------------------- config edges ------------------------------


def test_config_rejects_garbage_env_values(monkeypatch):
    monkeypatch.setenv("STADIUMIQ_RATE_LIMIT", "not-a-number")
    assert load_settings().rate_limit_per_minute == 30  # falls back to default


def test_config_clamps_below_minimum(monkeypatch):
    monkeypatch.setenv("STADIUMIQ_RATE_LIMIT", "0")
    assert load_settings().rate_limit_per_minute == 1  # minimum enforced


# --------------------------- assistant seams -----------------------------


def test_claude_property_disables_itself_when_sdk_missing(monkeypatch):
    # A key is configured but the SDK import fails -> assistant must
    # permanently switch to the offline engine instead of crashing.
    monkeypatch.setitem(sys.modules, "anthropic", None)
    assistant = Assistant(make_settings(anthropic_api_key="key-set"))
    assert assistant.engine_name == "claude"  # optimistic until first use
    assert assistant.claude is None
    assert assistant.engine_name == "local"  # disabled after the failed import


def test_docs_page_skips_csp_but_keeps_other_headers(client):
    res = client.get("/docs")
    assert res.status_code == 200
    assert "Content-Security-Policy" not in res.headers  # Swagger needs its CDN
    assert res.headers["X-Frame-Options"] == "DENY"
