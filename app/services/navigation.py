"""Route finding inside a stadium.

Each venue's zones form a weighted, undirected graph (weights = walking
minutes). Edges carry a ``step_free`` flag; when a visitor asks for an
accessible route only step-free edges (ramps, elevators, level walkways) are
considered.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .knowledge import facilities_of_type, zones_by_id


@dataclass
class RouteStep:
    zone_id: str
    zone_name: str
    minutes_from_previous: float


@dataclass
class Route:
    origin: str
    destination: str
    total_minutes: float
    accessible: bool
    steps: List[RouteStep] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "origin": self.origin,
            "destination": self.destination,
            "total_minutes": round(self.total_minutes, 1),
            "accessible": self.accessible,
            "steps": [
                {"zone_id": s.zone_id, "zone_name": s.zone_name, "minutes": round(s.minutes_from_previous, 1)}
                for s in self.steps
            ],
        }


def _adjacency(venue: Dict[str, Any], accessible: bool) -> Dict[str, List[Tuple[str, float]]]:
    graph: Dict[str, List[Tuple[str, float]]] = {z["id"]: [] for z in venue["zones"]}
    for frm, to, minutes, step_free in venue["edges"]:
        if accessible and not step_free:
            continue
        graph[frm].append((to, float(minutes)))
        graph[to].append((frm, float(minutes)))
    return graph


def _dijkstra(
    venue: Dict[str, Any], origin: str, accessible: bool
) -> Tuple[Dict[str, float], Dict[str, Optional[str]]]:
    graph = _adjacency(venue, accessible)
    dist: Dict[str, float] = {origin: 0.0}
    prev: Dict[str, Optional[str]] = {origin: None}
    heap: List[Tuple[float, str]] = [(0.0, origin)]
    while heap:
        d, node = heapq.heappop(heap)
        if d > dist.get(node, float("inf")):
            continue
        for neighbour, weight in graph.get(node, []):
            candidate = d + weight
            if candidate < dist.get(neighbour, float("inf")):
                dist[neighbour] = candidate
                prev[neighbour] = node
                heapq.heappush(heap, (candidate, neighbour))
    return dist, prev


def shortest_route(
    venue: Dict[str, Any], origin_id: str, destination_id: str, accessible: bool = False
) -> Optional[Route]:
    zones = zones_by_id(venue)
    if origin_id not in zones or destination_id not in zones:
        return None
    if origin_id == destination_id:
        return Route(origin_id, destination_id, 0.0, accessible, [RouteStep(origin_id, zones[origin_id]["name"], 0.0)])

    dist, prev = _dijkstra(venue, origin_id, accessible)
    if destination_id not in dist:
        return None

    path: List[str] = []
    node: Optional[str] = destination_id
    while node is not None:
        path.append(node)
        node = prev[node]
    path.reverse()

    steps = [RouteStep(path[0], zones[path[0]]["name"], 0.0)]
    for a, b in zip(path, path[1:]):
        steps.append(RouteStep(b, zones[b]["name"], dist[b] - dist[a]))
    return Route(origin_id, destination_id, dist[destination_id], accessible, steps)


def nearest_facilities(
    venue: Dict[str, Any],
    origin_id: str,
    ftype: str,
    accessible: bool = False,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Facilities of a type ranked by walking time from ``origin_id``."""
    zones = zones_by_id(venue)
    if origin_id not in zones:
        return []
    dist, _ = _dijkstra(venue, origin_id, accessible)
    ranked = []
    for facility in facilities_of_type(venue, ftype):
        minutes = dist.get(facility["zone"])
        if minutes is None:
            continue
        ranked.append(
            {
                "name": facility["name"],
                "type": facility["type"],
                "zone_id": facility["zone"],
                "zone_name": zones[facility["zone"]]["name"],
                "minutes": round(minutes, 1),
            }
        )
    ranked.sort(key=lambda f: f["minutes"])
    return ranked[:limit]
