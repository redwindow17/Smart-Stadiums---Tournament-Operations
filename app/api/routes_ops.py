"""Operations endpoints: crowd intelligence, AI advisory, incident triage."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..security import sanitize_text
from ..services import crowd as crowd_service
from ..services import knowledge
from .schemas import IncidentRequest

router = APIRouter(prefix="/api/ops", tags=["operations"])


def _venue_or_404(venue_id: str) -> dict:
    try:
        return knowledge.get_venue(venue_id)
    except knowledge.UnknownVenueError:
        raise HTTPException(status_code=404, detail="Unknown venue") from None


@router.get("/crowd")
def crowd(venue_id: str) -> dict:
    _venue_or_404(venue_id)
    snap = crowd_service.snapshot(venue_id)
    return {"snapshot": snap, "recommendations": crowd_service.recommendations(snap)}


@router.get("/advisory")
def advisory(request: Request, venue_id: str) -> dict:
    _venue_or_404(venue_id)
    return request.app.state.assistant.ops_advisory(venue_id)


@router.post("/incidents", status_code=201)
def create_incident(request: Request, payload: IncidentRequest) -> dict:
    state = request.app.state
    client = request.client.host if request.client else "unknown"
    if not state.rate_limiter.allow(f"incident:{client}"):
        raise HTTPException(status_code=429, detail="Too many requests - please slow down.")

    venue = _venue_or_404(payload.venue_id)
    zones = knowledge.zones_by_id(venue)
    if payload.zone_id not in zones:
        raise HTTPException(status_code=422, detail="Unknown zone for this venue")

    snap = crowd_service.snapshot(payload.venue_id)
    crowd_level = next((z["level"] for z in snap["zones"] if z["zone_id"] == payload.zone_id), "low")
    incident = state.incidents.create(
        venue_id=payload.venue_id,
        zone_id=payload.zone_id,
        zone_name=zones[payload.zone_id]["name"],
        category=payload.category,
        description=sanitize_text(payload.description, 500),
        severity_hint=payload.severity,
        crowd_level=crowd_level,
    )
    return {"incident": incident.to_dict()}


@router.get("/incidents")
def list_incidents(request: Request, venue_id: str) -> dict:
    _venue_or_404(venue_id)
    return {"incidents": [i.to_dict() for i in request.app.state.incidents.list(venue_id)]}
