"""Assistant orchestration: understand -> ground -> generate.

For every chat message the server:

1. sanitises the text and detects language + intent (``app.ai.nlu``),
2. computes only the *relevant* grounding from structured venue data
   (a route, nearby facilities, a crowd snapshot, transport options...),
3. hands message + grounding to the best available engine - Claude when an
   API key is configured, otherwise the deterministic offline engine. Any
   Claude failure falls back to the offline engine transparently.

This "ground first, generate second" design keeps answers factual, keeps
token usage low, and makes the whole pipeline testable without a network.
"""
from __future__ import annotations

import contextlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

from ..ai import nlu
from ..ai.claude_engine import ClaudeEngine, EngineUnavailable
from ..ai.local_engine import LocalEngine
from ..config import Settings
from ..security import sanitize_text
from . import crowd as crowd_service
from . import knowledge, navigation

logger = logging.getLogger("stadiumiq.assistant")

# Cue words that mark a mentioned zone as destination ("to Gate C") or origin
# ("from Gate A") in en / es / fr. Used to orient two-zone route requests.
_TO_CUES = {"to", "a", "al", "à", "hasta", "vers", "jusqu'à"}
_FROM_CUES = {"from", "desde", "de", "del", "depuis"}
_TOKEN = re.compile(r"[\w'à-ÿ]+")


class Assistant:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.local = LocalEngine()
        self._claude: ClaudeEngine | None = None
        self._claude_disabled = not settings.anthropic_api_key

    @property
    def claude(self) -> ClaudeEngine | None:
        if self._claude is None and not self._claude_disabled:
            try:
                self._claude = ClaudeEngine(self.settings)
            except EngineUnavailable as exc:
                logger.warning("Claude engine unavailable (%s); using offline engine", exc)
                self._claude_disabled = True
        return self._claude

    @property
    def engine_name(self) -> str:
        return "claude" if not self._claude_disabled else "local"

    # ------------------------------------------------------------------ chat

    def answer(
        self,
        *,
        message: str,
        venue_id: str,
        language: str = "auto",
        accessible: bool = False,
        location_zone: str | None = None,
        history: list[dict[str, str]] | None = None,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        venue = knowledge.get_venue(venue_id)  # raises UnknownVenueError
        msg = sanitize_text(message, self.settings.max_message_length)
        lang = nlu.detect_language(msg, language)
        zone_hits = knowledge.find_zones_in_text(venue, msg)
        ftype = nlu.facility_type_from_text(msg)
        accessible = accessible or nlu.wants_accessible(msg)
        intent = nlu.classify_intent(msg, ftype, len(zone_hits))

        zones = knowledge.zones_by_id(venue)
        default_location = venue.get("default_location", venue["zones"][0]["id"])
        origin = location_zone if location_zone in zones else default_location

        context: dict[str, Any] = {
            "venue": {"id": venue["id"], "name": venue["name"], "city": venue["city"], "country": venue["country"]},
            "language": lang,
            "intent": intent,
            "accessible": accessible,
            "origin_name": zones[origin]["name"],
        }
        data: dict[str, Any] = {}
        now = at or datetime.now(timezone.utc)

        if intent == "navigation":
            self._ground_navigation(context, data, venue, msg, origin, accessible, now)
        elif intent == "facility":
            self._ground_facility(context, data, venue, origin, ftype, accessible)
        elif intent == "crowd":
            crowd = self._crowd_lite(venue_id, now)
            context["crowd"] = crowd
            data["crowd"] = crowd
        elif intent == "transport":
            context["transport"] = venue["transport"]
            data["transport"] = venue["transport"]
        elif intent == "match":
            match = self._match_lite(venue_id, now)
            context["match"] = match
            data["match"] = match
        elif intent == "accessibility":
            context["accessibility"] = venue["accessibility"]
        elif intent == "sustainability":
            context["sustainability"] = venue["sustainability"]

        reply, engine_used = self._generate(msg, context, history)
        return {"reply": reply, "intent": intent, "language": lang, "engine": engine_used, "data": data}

    # -------------------------------------------------------------- grounding

    def _ground_navigation(self, context, data, venue, msg, origin, accessible, now) -> None:
        mentions = knowledge.find_zone_positions(venue, msg)
        if len(mentions) >= 2:
            origin_id, dest_id = self._orient(msg.lower(), mentions[0], mentions[1])
        elif len(mentions) == 1:
            origin_id, dest_id = origin, mentions[0][0]
        else:
            origin_id, dest_id = origin, None

        context["route_requested"] = dest_id is not None
        route = None
        if dest_id is not None:
            found = navigation.shortest_route(venue, origin_id, dest_id, accessible)
            route = found.to_dict() if found else None
        context["route"] = route
        if route:
            data["route"] = route
        crowd = self._crowd_lite(venue["id"], now)
        context["crowd"] = crowd

    @staticmethod
    def _orient(lowered: str, first: tuple, second: tuple) -> tuple[str, str]:
        """Decide origin vs destination for two mentioned zones.

        Default order is (first, second) - as in "from Gate A to the South
        Concourse" - but cue words flip it for "way to X from Y" phrasing.
        """

        def preceding_tokens(index: int) -> set:
            return set(_TOKEN.findall(lowered[:index])[-2:])

        if (_TO_CUES & preceding_tokens(first[1])) or (_FROM_CUES & preceding_tokens(second[1])):
            return second[0], first[0]
        return first[0], second[0]

    def _ground_facility(self, context, data, venue, origin, ftype, accessible) -> None:
        effective = ftype or "info_desk"
        if effective == "restroom" and accessible and knowledge.facilities_of_type(venue, "accessible_restroom"):
            effective = "accessible_restroom"
        facilities = navigation.nearest_facilities(venue, origin, effective, accessible)
        if not facilities and effective != ftype and ftype:
            effective = ftype
            facilities = navigation.nearest_facilities(venue, origin, effective, accessible)
        context["facility_type"] = effective
        context["facilities"] = facilities
        if facilities:
            data["facilities"] = facilities

    def _crowd_lite(self, venue_id: str, now: datetime) -> dict[str, Any]:
        snap = crowd_service.snapshot(venue_id, now)
        by_id = {z["zone_id"]: z for z in snap["zones"]}
        busiest = by_id.get(snap["busiest_gate"]) or {"zone_name": "-", "density": 0.0}
        quietest = by_id.get(snap["quietest_gate"]) or {"zone_name": "-", "density": 0.0}
        return {
            "phase": snap["phase"],
            "busiest": {"name": busiest["zone_name"], "pct": int(busiest["density"] * 100)},
            "quietest": {"name": quietest["zone_name"], "pct": int(quietest["density"] * 100)},
            "gates": [
                {"name": z["zone_name"], "pct": int(z["density"] * 100), "level": z["level"], "trend": z["trend"]}
                for z in snap["zones"]
                if z["kind"] == "gate"
            ],
        }

    def _match_lite(self, venue_id: str, now: datetime) -> dict[str, Any] | None:
        match = knowledge.next_match(venue_id, now)
        if not match:
            return None
        status = "live" if match["kickoff"] <= now < match["kickoff"] + knowledge.MATCH_DURATION else "upcoming"
        return {
            "stage": match["stage"],
            "home": match["home"],
            "away": match["away"],
            "kickoff": match["kickoff"].strftime("%a %d %b, %H:%M UTC"),
            "status": status,
        }

    # -------------------------------------------------------------- generate

    def _generate(
        self, message: str, context: dict[str, Any], history: list[dict[str, str]] | None
    ) -> tuple[str, str]:
        engine = self.claude
        if engine is not None:
            try:
                return engine.generate(message, context, history), engine.name
            except EngineUnavailable:
                pass  # already logged; degrade gracefully
        return self.local.generate(message, context, history), self.local.name

    # ------------------------------------------------------------------- ops

    def ops_advisory(self, venue_id: str, at: datetime | None = None) -> dict[str, Any]:
        snap = crowd_service.snapshot(venue_id, at)
        recs = crowd_service.recommendations(snap)
        engine = self.claude
        brief, engine_used = None, self.local.name
        if engine is not None:
            with contextlib.suppress(EngineUnavailable):
                brief, engine_used = engine.ops_brief(snap, recs), engine.name
        if brief is None:
            brief = self.local.ops_brief(snap, recs)
        return {"snapshot": snap, "recommendations": recs, "brief": brief, "engine": engine_used}
