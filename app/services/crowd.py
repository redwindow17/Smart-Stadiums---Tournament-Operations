"""Crowd intelligence: per-zone density estimates and operational advice.

There is no live sensor feed in a hackathon, so densities are *simulated* -
but deterministically: the value for (venue, zone, 10-minute bucket) is a
hash, scaled by the current match phase (ingress / in-match / egress / quiet)
and the zone kind (gates spike around ingress/egress, concourses during the
match). Determinism makes the behaviour testable and reproducible while still
looking and moving like a real feed. Swapping this module for a real
sensor/turnstile feed changes nothing upstream.
"""
from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .knowledge import get_venue, match_phase

BUCKET_SECONDS = 600  # 10-minute buckets -> stable values, visible movement

# (offset, spread) applied to the 0..1 hash value, per phase and zone kind.
_PHASE_PROFILE: Dict[str, Dict[str, Tuple[float, float]]] = {
    "ingress": {"gate": (0.45, 0.50), "concourse": (0.30, 0.40), "external": (0.35, 0.45)},
    "in_match": {"gate": (0.05, 0.15), "concourse": (0.30, 0.50), "external": (0.05, 0.20)},
    "egress": {"gate": (0.50, 0.50), "concourse": (0.40, 0.40), "external": (0.45, 0.50)},
    "quiet": {"gate": (0.02, 0.18), "concourse": (0.02, 0.18), "external": (0.02, 0.18)},
}

_LEVELS = [(0.35, "low"), (0.60, "moderate"), (0.80, "high"), (2.0, "critical")]

_cache: Dict[Tuple[str, int], Dict[str, Any]] = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 32


def level_for(density: float) -> str:
    for threshold, label in _LEVELS:
        if density < threshold:
            return label
    return "critical"


def _bucket(at: datetime) -> int:
    return int(at.timestamp()) // BUCKET_SECONDS


def _raw(venue_id: str, zone_id: str, bucket: int) -> float:
    digest = hashlib.sha256(f"{venue_id}:{zone_id}:{bucket}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32


def _density(venue_id: str, zone_id: str, kind: str, bucket: int, phase: str) -> float:
    offset, spread = _PHASE_PROFILE[phase].get(kind, (0.05, 0.2))
    return round(min(1.0, offset + _raw(venue_id, zone_id, bucket) * spread), 3)


def snapshot(venue_id: str, at: Optional[datetime] = None) -> Dict[str, Any]:
    """Density snapshot for all crowd-relevant zones of a venue."""
    now = at or datetime.now(timezone.utc)
    bucket = _bucket(now)
    key = (venue_id, bucket)
    with _cache_lock:
        if key in _cache:
            return _cache[key]

    venue = get_venue(venue_id)
    phase = match_phase(venue_id, now)
    zones: List[Dict[str, Any]] = []
    for zone in venue["zones"]:
        if zone["kind"] not in ("gate", "concourse", "external"):
            continue
        density = _density(venue_id, zone["id"], zone["kind"], bucket, phase)
        previous = _density(venue_id, zone["id"], zone["kind"], bucket - 1, phase)
        trend = "rising" if density - previous > 0.05 else "falling" if previous - density > 0.05 else "steady"
        zones.append(
            {
                "zone_id": zone["id"],
                "zone_name": zone["name"],
                "kind": zone["kind"],
                "density": density,
                "level": level_for(density),
                "trend": trend,
            }
        )

    gates = [z for z in zones if z["kind"] == "gate"]
    result = {
        "venue_id": venue_id,
        "phase": phase,
        "generated_at": now.isoformat(),
        "zones": zones,
        "busiest_gate": max(gates, key=lambda z: z["density"])["zone_id"] if gates else None,
        "quietest_gate": min(gates, key=lambda z: z["density"])["zone_id"] if gates else None,
    }

    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[key] = result
    return result


def recommendations(snap: Dict[str, Any]) -> List[Dict[str, str]]:
    """Rule-based operational advice derived from a crowd snapshot."""
    advice: List[Dict[str, str]] = []
    zones = snap["zones"]
    gates = [z for z in zones if z["kind"] == "gate"]
    concourses = [z for z in zones if z["kind"] == "concourse"]
    quietest = min(gates, key=lambda z: z["density"]) if gates else None

    for gate in gates:
        if gate["level"] == "critical" and quietest and quietest["zone_id"] != gate["zone_id"]:
            advice.append(
                {
                    "priority": "P1",
                    "action": f"Redirect arriving fans from {gate['zone_name']} to {quietest['zone_name']}",
                    "reason": f"{gate['zone_name']} at {int(gate['density'] * 100)}% density ({gate['trend']}); "
                    f"{quietest['zone_name']} at {int(quietest['density'] * 100)}%.",
                }
            )
        elif gate["level"] == "high":
            advice.append(
                {
                    "priority": "P2",
                    "action": f"Open extra screening lanes and add stewards at {gate['zone_name']}",
                    "reason": f"Density {int(gate['density'] * 100)}% and {gate['trend']}.",
                }
            )

    for concourse in concourses:
        if concourse["level"] == "critical":
            advice.append(
                {
                    "priority": "P1",
                    "action": f"Enforce one-way pedestrian flow in {concourse['zone_name']}",
                    "reason": f"Density {int(concourse['density'] * 100)}% - crush risk if unmanaged.",
                }
            )
        elif concourse["level"] == "high":
            advice.append(
                {
                    "priority": "P2",
                    "action": f"Stagger concession queues in {concourse['zone_name']}",
                    "reason": f"Density {int(concourse['density'] * 100)}%.",
                }
            )

    if snap["phase"] == "egress" and gates and sum(g["density"] for g in gates) / len(gates) > 0.6:
        advice.append(
            {
                "priority": "P2",
                "action": "Start block-by-block hold-and-release egress; request extra transit service",
                "reason": "Average gate density above 60% during egress.",
            }
        )

    if not advice:
        advice.append(
            {
                "priority": "P3",
                "action": "No intervention needed - continue routine monitoring",
                "reason": "All zones within normal density bands.",
            }
        )
    advice.sort(key=lambda a: a["priority"])
    return advice
