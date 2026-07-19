"""Venue knowledge base: stadium layouts, facilities, transport and fixtures.

The data ships as JSON under ``app/data`` and is loaded exactly once
(``lru_cache``). Everything the assistant says is grounded in this structured
data, which keeps generated answers factual and keeps token usage small.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Match-day phases relative to kickoff (UTC).
INGRESS_WINDOW = timedelta(hours=4)
MATCH_DURATION = timedelta(hours=2)
EGRESS_WINDOW = timedelta(hours=2)


class UnknownVenueError(KeyError):
    """Raised when a venue id does not exist in the knowledge base."""


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    with open(DATA_DIR / "stadiums.json", encoding="utf-8") as fh:
        stadiums = json.load(fh)
    with open(DATA_DIR / "matches.json", encoding="utf-8") as fh:
        matches = json.load(fh)
    venues = {v["id"]: v for v in stadiums["venues"]}
    for match in matches["matches"]:
        match["kickoff"] = datetime.fromisoformat(match["kickoff_utc"].replace("Z", "+00:00"))
    return {"venues": venues, "matches": matches["matches"]}


def list_venues() -> list[dict[str, Any]]:
    return [
        {"id": v["id"], "name": v["name"], "city": v["city"], "country": v["country"], "capacity": v["capacity"]}
        for v in _load()["venues"].values()
    ]


def get_venue(venue_id: str) -> dict[str, Any]:
    try:
        return _load()["venues"][venue_id]
    except KeyError as exc:
        raise UnknownVenueError(venue_id) from exc


def zones_by_id(venue: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {z["id"]: z for z in venue["zones"]}


def find_zone_positions(venue: dict[str, Any], text: str) -> list[tuple]:
    """Zones mentioned in ``text`` as ``(zone_id, char_index)`` pairs, ordered
    by first appearance. Matching is alias-based and case-insensitive."""
    lowered = text.lower()
    found: dict[str, int] = {}
    for zone in venue["zones"]:
        aliases = [zone["name"].lower(), *[a.lower() for a in zone.get("aliases", [])]]
        best = -1
        for alias in aliases:
            idx = lowered.find(alias)
            if idx >= 0 and (best == -1 or idx < best):
                best = idx
        if best >= 0:
            found[zone["id"]] = best
    return sorted(found.items(), key=lambda kv: kv[1])


def find_zones_in_text(venue: dict[str, Any], text: str) -> list[str]:
    """Zone ids mentioned in ``text``, ordered by first appearance."""
    return [zone_id for zone_id, _ in find_zone_positions(venue, text)]


def facilities_of_type(venue: dict[str, Any], ftype: str) -> list[dict[str, Any]]:
    return [f for f in venue["facilities"] if f["type"] == ftype]


def matches_for_venue(venue_id: str) -> list[dict[str, Any]]:
    return [m for m in _load()["matches"] if m["venue_id"] == venue_id]


def next_match(venue_id: str, at: datetime | None = None) -> dict[str, Any] | None:
    """The match currently in progress at the venue, or the next one to start."""
    now = at or datetime.now(timezone.utc)
    candidates = [m for m in matches_for_venue(venue_id) if m["kickoff"] + MATCH_DURATION >= now]
    return min(candidates, key=lambda m: m["kickoff"]) if candidates else None


def match_phase(venue_id: str, at: datetime | None = None) -> str:
    """Classify the current moment: ingress / in_match / egress / quiet."""
    now = at or datetime.now(timezone.utc)
    for m in matches_for_venue(venue_id):
        delta = now - m["kickoff"]
        if -INGRESS_WINDOW <= delta < timedelta(0):
            return "ingress"
        if timedelta(0) <= delta < MATCH_DURATION:
            return "in_match"
        if MATCH_DURATION <= delta < MATCH_DURATION + EGRESS_WINDOW:
            return "egress"
    return "quiet"
