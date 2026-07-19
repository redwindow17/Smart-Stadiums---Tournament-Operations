"""Routing: shortest paths, step-free filtering, facility ranking."""
from app.services import knowledge, navigation


def venue():
    return knowledge.get_venue("azteca")


def test_route_between_hub_and_south_concourse():
    route = navigation.shortest_route(venue(), "transport_hub", "concourse_south")
    assert route is not None
    assert route.steps[0].zone_id == "transport_hub"
    assert route.steps[-1].zone_id == "concourse_south"
    assert route.total_minutes > 0
    # Step minutes must sum to the total.
    assert abs(sum(s.minutes_from_previous for s in route.steps) - route.total_minutes) < 1e-6


def test_same_zone_route_is_zero_minutes():
    route = navigation.shortest_route(venue(), "gate_a", "gate_a")
    assert route is not None
    assert route.total_minutes == 0


def test_accessible_route_uses_step_free_edge():
    # North Concourse -> North Stand: 2 min via stairs, 4 min via elevator.
    stairs = navigation.shortest_route(venue(), "concourse_north", "stand_north", accessible=False)
    step_free = navigation.shortest_route(venue(), "concourse_north", "stand_north", accessible=True)
    assert stairs is not None and step_free is not None
    assert stairs.total_minutes == 2
    assert step_free.total_minutes == 4


def test_every_zone_reachable_step_free():
    """Accessibility guarantee: the step-free graph must be fully connected."""
    for v in [knowledge.get_venue(item["id"]) for item in knowledge.list_venues()]:
        for zone in v["zones"]:
            route = navigation.shortest_route(v, v["default_location"], zone["id"], accessible=True)
            assert route is not None, f"{v['id']}: no step-free route to {zone['id']}"


def test_unknown_zone_returns_none():
    assert navigation.shortest_route(venue(), "transport_hub", "vip_lounge") is None


def test_nearest_facilities_sorted_by_walk_time():
    results = navigation.nearest_facilities(venue(), "transport_hub", "restroom")
    assert results
    minutes = [r["minutes"] for r in results]
    assert minutes == sorted(minutes)


def test_nearest_accessible_restroom_exists_everywhere():
    for item in knowledge.list_venues():
        v = knowledge.get_venue(item["id"])
        results = navigation.nearest_facilities(v, v["default_location"], "accessible_restroom", accessible=True)
        assert results, f"{v['id']}: no step-free accessible restroom"
