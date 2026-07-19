"""Crowd simulation: determinism, bounds, phases, recommendations."""
from app.services import crowd, knowledge

from .conftest import INGRESS_AT_METLIFE, QUIET_EVERYWHERE


def test_snapshot_is_deterministic():
    a = crowd.snapshot("metlife", INGRESS_AT_METLIFE)
    b = crowd.snapshot("metlife", INGRESS_AT_METLIFE)
    assert a == b


def test_phase_detection():
    assert knowledge.match_phase("metlife", INGRESS_AT_METLIFE) == "ingress"
    assert knowledge.match_phase("azteca", INGRESS_AT_METLIFE) == "quiet"
    assert knowledge.match_phase("metlife", QUIET_EVERYWHERE) == "quiet"


def test_densities_within_bounds():
    snap = crowd.snapshot("metlife", INGRESS_AT_METLIFE)
    assert snap["zones"], "snapshot should include zones"
    for zone in snap["zones"]:
        assert 0.0 <= zone["density"] <= 1.0
        assert zone["level"] in ("low", "moderate", "high", "critical")
        assert zone["trend"] in ("rising", "falling", "steady")


def test_level_thresholds():
    assert crowd.level_for(0.1) == "low"
    assert crowd.level_for(0.5) == "moderate"
    assert crowd.level_for(0.7) == "high"
    assert crowd.level_for(0.95) == "critical"


def test_busiest_and_quietest_gates_identified():
    snap = crowd.snapshot("azteca", INGRESS_AT_METLIFE)
    gates = {z["zone_id"]: z["density"] for z in snap["zones"] if z["kind"] == "gate"}
    assert snap["busiest_gate"] in gates
    assert gates[snap["busiest_gate"]] == max(gates.values())
    assert gates[snap["quietest_gate"]] == min(gates.values())


def test_recommendations_never_empty():
    snap = crowd.snapshot("metlife", INGRESS_AT_METLIFE)
    recs = crowd.recommendations(snap)
    assert recs
    assert all(r["priority"] in ("P1", "P2", "P3") for r in recs)


def test_quiet_phase_needs_no_intervention():
    snap = crowd.snapshot("azteca", QUIET_EVERYWHERE)
    recs = crowd.recommendations(snap)
    assert all(r["priority"] == "P3" for r in recs)
