import os
import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

os.environ["SENTINEL_DECISIONS_MOCK"] = "1"

from server import app as server_app


@pytest.fixture(scope="module")
def client():
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql://sentinel:sentinel@localhost:5432/sentinel"
    )
    parsed = urlparse(database_url)
    try:
        with socket.create_connection(
            (parsed.hostname or "localhost", parsed.port or 5432), timeout=0.5
        ):
            pass
    except OSError:
        pytest.skip("Postgres is not reachable")

    with TestClient(server_app.app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def reset_memory_state():
    server_app.S.missions.clear()
    server_app.S.stop_flag = False
    server_app.S.drone = server_app.DroneState()
    server_app.S.agent_runs.clear()


def unique_id():
    return uuid4().hex


def test_health_site_and_products(client):
    assert client.get("/api/health").json() == {"ok": True}

    site = client.get("/api/site")
    assert site.status_code == 200
    assert site.json()["zones"]

    products = client.get("/api/products")
    assert products.status_code == 200
    rows = products.json()
    assert len(rows) == 20
    assert all(
        {"product_id", "name", "brand", "barcode", "price_gbp", "zone_id"} <= row.keys()
        for row in rows
    )


def test_events_insert_filter_order_heatmap_and_funnel(client):
    track_id = unique_id()
    zone_id = f"test-zone-{track_id}"
    now = datetime.now(UTC).replace(microsecond=0)
    older = (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    newer = now.isoformat().replace("+00:00", "Z")
    single = {
        "ts": older,
        "zone_id": zone_id,
        "type": "look",
        "source": "sim",
        "track_id": track_id,
        "payload": {"duration_s": 2, "gaze_hit_xyz": [1, 2, 3]},
    }
    response = client.post("/api/events", json=single)
    assert response.status_code == 200
    assert response.json()["inserted"] == 1
    assert len(response.json()["event_ids"]) == 1

    batch = [
        {
            "ts": newer,
            "zone_id": zone_id,
            "type": "look",
            "source": "sim",
            "track_id": track_id,
            "x": 4,
            "y": 5,
            "payload": {"duration_s": 3},
        },
        {
            "ts": newer,
            "zone_id": zone_id,
            "type": "interest",
            "source": "sim",
            "track_id": track_id,
            "payload": {"duration_s": 7},
        },
    ]
    response = client.post("/api/events", json=batch)
    assert response.status_code == 200
    assert response.json()["inserted"] == 2
    assert len(response.json()["event_ids"]) == 2

    events = client.get(
        "/api/events",
        params={"type": "look", "zone_id": zone_id, "limit": 2},
    )
    assert events.status_code == 200
    assert [event["ts"] for event in events.json()] == [newer, older]

    heatmap = client.get("/api/heatmap").json()
    assert {"zones", "points"} <= heatmap.keys()
    assert heatmap["zones"][zone_id] == {"look_s": 5.0, "looks": 2}

    funnel = client.get("/api/funnel").json()
    expected_keys = {
        "product_id",
        "name",
        "zone_id",
        "passed_by",
        "looked",
        "interested",
        "picked_up",
        "put_back",
        "kept",
        "sold",
        "put_back_rate",
        "flag_high_attention_low_conversion",
    }
    assert funnel
    assert all(set(row) == expected_keys for row in funnel)


def test_task_create_list_and_patch(client):
    zone_id = f"test-task-zone-{unique_id()}"
    created = client.post(
        "/api/tasks",
        json={"zone_id": zone_id, "kind": "restock", "severity": 0.7, "note": "test"},
    )
    assert created.status_code == 200
    task = created.json()
    assert task["zone_id"] == zone_id
    assert task["status"] == "open"
    assert task in client.get("/api/tasks", params={"status": "open"}).json()

    patched = client.patch(
        f"/api/tasks/{task['task_id']}",
        json={"status": "in_progress", "assignee": "tester", "note": "working"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "in_progress"
    assert patched.json()["assignee"] == "tester"
    assert patched.json()["note"] == "working"


def test_review_flow(client):
    event_id = unique_id()
    event = {
        "event_id": event_id,
        "zone_id": f"review-zone-{unique_id()}",
        "type": "look",
        "decision": {"question": "reach_outcome", "answer": {}, "policy": "review"},
        "payload": {"duration_s": 1},
    }
    assert client.post("/api/events", json=event).json()["inserted"] == 1
    assert event_id in {row["event_id"] for row in client.get("/api/review").json()}

    reviewed = client.post(
        f"/api/review/{event_id}", json={"verdict": "confirm", "label": "correct"}
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["payload"]["review"]["verdict"] == "confirm"
    assert event_id not in {row["event_id"] for row in client.get("/api/review").json()}


def test_drone_state_missions_and_stop(client):
    state = {
        "mode": "sim",
        "state": "IDLE",
        "x": 1,
        "y": 2,
        "z": 1.5,
        "battery_pct": 90,
    }
    assert client.post("/api/drone/state", json=state).json() == {"ok": True}
    assert client.get("/api/drone/state").json()["battery_pct"] == 90

    invalid = client.post(
        "/api/drone/mission",
        json={"bays": ["bay-not-real"], "reason": "test", "requested_by": "user"},
    )
    assert invalid.status_code == 200
    assert invalid.json()["accepted"] is False
    assert invalid.json()["rejected_reason"]

    accepted = client.post(
        "/api/drone/mission",
        json={"bays": ["bay-B-01"], "reason": "test", "requested_by": "user"},
    )
    assert accepted.json()["accepted"] is True
    mission = client.get("/api/drone/mission").json()
    assert mission["mission_id"] == accepted.json()["mission_id"]
    assert mission["bays"] == ["bay-B-01"]

    stopped = client.post("/api/drone/stop")
    assert stopped.json() == {"ok": True}
    assert client.get("/api/drone/state").json()["stop_requested"] is True
    assert client.get("/api/drone/mission").json() is None


def test_ask_summary_and_agent_endpoints(client):
    ask = client.post("/api/ask", json={"question": "which drone battery"})
    assert ask.status_code == 200
    assert {"answer", "intent", "data"} <= ask.json().keys()
    assert ask.json()["intent"] == "drone_status"

    summary = client.get("/api/summary")
    assert summary.status_code == 200
    assert isinstance(summary.json()["text"], str)
    assert isinstance(summary.json()["open_tasks"], int)

    runs = client.get("/api/agent/runs")
    assert runs.status_code == 200
    assert isinstance(runs.json(), list)
    unavailable = client.post("/api/agent/run", json={"goal": "test"})
    assert unavailable.status_code == 503


def test_websocket_receives_initial_drone_and_posted_event(client):
    with client.websocket_connect("/ws") as websocket:
        initial = websocket.receive_json()
        assert initial["kind"] == "drone"
        assert "battery_pct" in initial["data"]

        response = client.post(
            "/api/events",
            json={
                "zone_id": f"ws-zone-{unique_id()}",
                "type": "pass_by",
                "track_id": unique_id(),
            },
        )
        assert response.status_code == 200
        message = websocket.receive_json()
        assert message["kind"] == "event"
        assert message["data"]["type"] == "pass_by"
