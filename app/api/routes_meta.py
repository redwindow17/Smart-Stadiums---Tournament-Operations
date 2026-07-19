"""Health check and venue metadata endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .. import __version__
from ..services import knowledge

router = APIRouter(prefix="/api", tags=["meta"])


def _venue_or_404(venue_id: str) -> dict:
    try:
        return knowledge.get_venue(venue_id)
    except knowledge.UnknownVenueError:
        raise HTTPException(status_code=404, detail="Unknown venue")


@router.get("/health")
def health(request: Request) -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "engine": request.app.state.assistant.engine_name,
    }


@router.get("/venues")
def venues() -> dict:
    return {"venues": knowledge.list_venues()}


@router.get("/venues/{venue_id}")
def venue_detail(venue_id: str) -> dict:
    venue = _venue_or_404(venue_id)
    return {
        "id": venue["id"],
        "name": venue["name"],
        "city": venue["city"],
        "country": venue["country"],
        "capacity": venue["capacity"],
        "default_location": venue.get("default_location"),
        "zones": [{"id": z["id"], "name": z["name"], "kind": z["kind"]} for z in venue["zones"]],
        "facilities": venue["facilities"],
        "transport": venue["transport"],
        "accessibility": venue["accessibility"],
        "sustainability": venue["sustainability"],
    }


@router.get("/venues/{venue_id}/matches")
def venue_matches(venue_id: str) -> dict:
    _venue_or_404(venue_id)
    return {
        "matches": [
            {"id": m["id"], "stage": m["stage"], "home": m["home"], "away": m["away"], "kickoff_utc": m["kickoff_utc"]}
            for m in knowledge.matches_for_venue(venue_id)
        ]
    }
