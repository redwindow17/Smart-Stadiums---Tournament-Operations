"""Incident intake and triage for venue staff.

Triage is deliberately rule-based (transparent, auditable, instant); the AI
layer adds a natural-language action brief on top rather than making the
safety-critical priority call.
"""
from __future__ import annotations

import builtins
import itertools
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

CATEGORY_WEIGHTS: dict[str, int] = {
    "medical": 5,
    "crowd_crush": 5,
    "fire_hazard": 5,
    "security": 4,
    "lost_child": 4,
    "accessibility": 3,
    "technical": 2,
    "cleaning": 1,
    "lost_item": 1,
}

# Categories where surrounding crowd pressure escalates the response.
_CROWD_SENSITIVE = {"medical", "crowd_crush", "security", "fire_hazard"}

PLAYBOOK: dict[str, list[str]] = {
    "medical": [
        "Dispatch nearest first-aid team with AED",
        "Clear a 5 m working perimeter and an evacuation corridor",
        "Alert on-site medical centre to prepare for handover",
    ],
    "crowd_crush": [
        "Stop inbound flow to the affected zone immediately",
        "Open all adjacent relief gates / exits",
        "Broadcast calm-movement announcement in EN / ES / FR",
    ],
    "fire_hazard": [
        "Send fire marshal to verify and isolate the source",
        "Pre-stage evacuation route signage for the zone",
        "Notify venue control room and local fire service",
    ],
    "security": [
        "Send two stewards plus one security officer to observe",
        "Begin discreet CCTV tracking of the subject(s)",
        "Escalate to police liaison if behaviour continues",
    ],
    "lost_child": [
        "Activate lost-child protocol: description to all radios",
        "Post stewards at every gate of the venue",
        "Bring guardian to the Safeguarding Point and log the case",
    ],
    "accessibility": [
        "Dispatch accessibility steward with wheelchair support",
        "Verify nearest elevator / ramp is operational",
        "Offer relocation to the accessible viewing platform",
    ],
    "technical": [
        "Create maintenance ticket and dispatch technician",
        "Place signage / barriers if equipment poses any hazard",
    ],
    "cleaning": [
        "Dispatch cleaning crew; place wet-floor signage",
    ],
    "lost_item": [
        "Log item description at the Info Desk lost-and-found",
        "Advise reporter to check the venue lost-property page post-match",
    ],
}

_id_counter = itertools.count(1)


@dataclass
class Incident:
    id: int
    venue_id: str
    zone_id: str
    zone_name: str
    category: str
    description: str
    score: int
    priority: str
    actions: list[str]
    crowd_level: str
    created_at: str
    status: str = "open"
    ai_brief: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def triage_score(category: str, severity_hint: int | None, crowd_level: str) -> int:
    base = CATEGORY_WEIGHTS.get(category, 2)
    score = max(base, severity_hint or 0)
    if crowd_level in ("high", "critical") and category in _CROWD_SENSITIVE:
        score += 1
    return max(1, min(5, score))


def priority_label(score: int) -> str:
    if score >= 5:
        return "critical"
    if score == 4:
        return "high"
    if score == 3:
        return "medium"
    return "low"


@dataclass
class IncidentLog:
    """Bounded in-memory incident store (per app instance)."""

    max_items: int = 200
    _items: deque[Incident] = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def create(
        self,
        venue_id: str,
        zone_id: str,
        zone_name: str,
        category: str,
        description: str,
        severity_hint: int | None,
        crowd_level: str,
    ) -> Incident:
        score = triage_score(category, severity_hint, crowd_level)
        incident = Incident(
            id=next(_id_counter),
            venue_id=venue_id,
            zone_id=zone_id,
            zone_name=zone_name,
            category=category,
            description=description,
            score=score,
            priority=priority_label(score),
            actions=list(PLAYBOOK.get(category, ["Dispatch a steward to assess on site"])),
            crowd_level=crowd_level,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._items.append(incident)
            while len(self._items) > self.max_items:
                self._items.popleft()
        return incident

    def list(self, venue_id: str | None = None) -> builtins.list[Incident]:
        with self._lock:
            items = list(self._items)
        if venue_id:
            items = [i for i in items if i.venue_id == venue_id]
        return sorted(items, key=lambda i: (-i.score, -i.id))
