"""End-to-end API tests (offline engine, in-process TestClient)."""


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["engine"] == "local"  # no API key in tests


def test_frontend_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "StadiumIQ" in res.text
    assert client.get("/ops.html").status_code == 200


def test_venues_list(client):
    body = client.get("/api/venues").json()
    ids = {v["id"] for v in body["venues"]}
    assert ids == {"azteca", "metlife", "bcplace"}


def test_venue_detail(client):
    body = client.get("/api/venues/bcplace").json()
    assert body["name"] == "BC Place"
    assert body["default_location"]
    assert body["zones"] and body["facilities"] and body["transport"]


def test_unknown_venue_is_404(client):
    assert client.get("/api/venues/wembley").status_code == 404
    assert client.get("/api/venues/wembley/matches").status_code == 404


def test_venue_matches(client):
    body = client.get("/api/venues/metlife/matches").json()
    stages = [m["stage"] for m in body["matches"]]
    assert "Final" in stages


def test_chat_happy_path(client):
    res = client.post(
        "/api/chat",
        json={"message": "How do I get to Gate C?", "venue_id": "azteca"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["reply"]
    assert body["engine"] == "local"
    assert body["intent"] == "navigation"


def test_chat_validation_errors(client):
    # empty message
    assert client.post("/api/chat", json={"message": "", "venue_id": "azteca"}).status_code == 422
    # oversized message
    assert (
        client.post("/api/chat", json={"message": "x" * 2001, "venue_id": "azteca"}).status_code
        == 422
    )
    # malformed venue id (pattern guard)
    assert (
        client.post("/api/chat", json={"message": "hi", "venue_id": "AZTECA!!"}).status_code == 422
    )
    # oversized history
    history = [{"role": "user", "content": "hi"}] * 13
    assert (
        client.post(
            "/api/chat", json={"message": "hi", "venue_id": "azteca", "history": history}
        ).status_code
        == 422
    )


def test_chat_unknown_venue_is_404(client):
    res = client.post("/api/chat", json={"message": "hi", "venue_id": "wembley"})
    assert res.status_code == 404


def test_ops_crowd(client):
    body = client.get("/api/ops/crowd", params={"venue_id": "metlife"}).json()
    assert body["snapshot"]["zones"]
    assert body["recommendations"]


def test_ops_advisory(client):
    body = client.get("/api/ops/advisory", params={"venue_id": "azteca"}).json()
    assert body["brief"]
    assert body["engine"] == "local"
    assert all({"priority", "action", "reason"} <= set(r) for r in body["recommendations"])


def test_incident_triage_flow(client):
    res = client.post(
        "/api/ops/incidents",
        json={
            "venue_id": "azteca",
            "zone_id": "concourse_north",
            "category": "medical",
            "description": "Fan collapsed near the food hall",
            "severity": 5,
        },
    )
    assert res.status_code == 201
    incident = res.json()["incident"]
    assert incident["priority"] == "critical"
    assert incident["actions"]

    listed = client.get("/api/ops/incidents", params={"venue_id": "azteca"}).json()["incidents"]
    assert any(i["id"] == incident["id"] for i in listed)


def test_incident_low_priority_category(client):
    res = client.post(
        "/api/ops/incidents",
        json={
            "venue_id": "bcplace",
            "zone_id": "concourse_south",
            "category": "lost_item",
            "description": "Left a scarf on my seat",
        },
    )
    assert res.status_code == 201
    assert res.json()["incident"]["priority"] == "low"


def test_incident_rejects_unknown_zone_and_category(client):
    bad_zone = client.post(
        "/api/ops/incidents",
        json={"venue_id": "azteca", "zone_id": "vip_lounge", "category": "medical", "description": "x"},
    )
    assert bad_zone.status_code == 422
    bad_category = client.post(
        "/api/ops/incidents",
        json={"venue_id": "azteca", "zone_id": "gate_a", "category": "alien_landing", "description": "x"},
    )
    assert bad_category.status_code == 422
