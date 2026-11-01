import json

import httpx
import pytest
from agent import sentinel_agent as agent
from agent import stub_server
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTINEL_AGENT_RUNS", str(tmp_path / "runs.json"))
    monkeypatch.setenv("SENTINEL_AGENT_MOCK", "0")
    monkeypatch.delenv("DEVIN_API_VERSION", raising=False)
    monkeypatch.setenv("DEVIN_API_BASE", "https://devin.example")


@pytest.mark.parametrize("key,version,create_path,status_path", [
    ("apk_example", "v1", "/v1/sessions", "/v1/session/devin-123"),
    ("cog_example", "v3", "/v3/organizations/org-123/sessions",
     "/v3/organizations/org-123/sessions/devin-123"),
])
def test_real_requests(monkeypatch, key, version, create_path, status_path):
    monkeypatch.setenv("DEVIN_API_KEY", key)
    monkeypatch.setenv("DEVIN_ORG_ID", "org-123")
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"session_id": "devin-123", "url": "https://app/session"})
        return httpx.Response(200, json={"status_enum": "working"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(agent.httpx, "request", client.request)
    assert agent.list_runs() == []
    result = agent.launch("stock check", "https://sentinel.example")
    assert result["session_id"] == "devin-123"
    assert requests[0].url.path == create_path
    assert requests[0].headers["Authorization"] == f"Bearer {key}"
    body = json.loads(requests[0].content)
    assert "stock check" in body["prompt"] and "https://sentinel.example" in body["prompt"]
    assert body["tags"] and body["title"]
    assert ("structured_output_schema" in body) == (version == "v3")
    assert agent.status("devin-123")["status"] == "working"
    assert requests[1].url.path == status_path
    assert agent.list_runs()[0]["status"] == "working"


def test_override_and_error(monkeypatch):
    monkeypatch.setenv("DEVIN_API_KEY", "cog_example")
    monkeypatch.setenv("DEVIN_API_VERSION", "v1")
    def handler(request):
        assert request.url.path == "/v1/sessions"
        return httpx.Response(401, json={"detail": "API key has expired or been revoked"})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(agent.httpx, "request", client.request)
    with pytest.raises(agent.DevinAPIError, match="401.*expired or been revoked"):
        agent.launch("goal", "https://sentinel.example")
    assert agent.list_runs() == []


def test_configuration_and_empty(monkeypatch):
    monkeypatch.delenv("DEVIN_API_KEY", raising=False)
    with pytest.raises(agent.DevinAPIError, match="DEVIN_API_KEY"):
        agent.launch("goal", "https://sentinel.example")
    with pytest.raises(ValueError):
        agent.launch("", "https://sentinel.example")
    with pytest.raises(KeyError):
        agent.status("missing")
    monkeypatch.setenv("DEVIN_API_KEY", "cog_test")
    monkeypatch.delenv("DEVIN_ORG_ID", raising=False)
    assert agent._api_config()[1].endswith(f"/v3/organizations/{agent.DEFAULT_ORG_ID}/sessions")


def test_mock_is_default(monkeypatch):
    monkeypatch.delenv("SENTINEL_AGENT_MOCK", raising=False)
    assert agent.is_mock()


def test_mock_end_to_end(monkeypatch):
    monkeypatch.setenv("SENTINEL_AGENT_MOCK", "1")
    monkeypatch.setattr(stub_server, "events", [
        {"event_id": "e1", "zone_id": "bay-B-01", "type": "bay_issue",
         "payload": {"issue": "empty", "severity": "act_now"}},
    ])
    monkeypatch.setattr(stub_server, "tasks", [])
    monkeypatch.setattr(stub_server, "mission", None)
    client = TestClient(stub_server.app)
    simulate = agent.simulate_mission
    monkeypatch.setattr(agent, "simulate_mission", lambda goal, base: simulate(goal, base, client))
    run = client.post("/api/agent/run", json={"goal": "check"}).json()
    assert agent.wait(run["session_id"])["status"] == "completed"
    assert client.get("/api/drone/mission").json()["bays"][0] == "bay-B-01"
    assert client.get("/api/tasks").json()[0]["source_event"] == "e1"
    assert client.get("/api/events", params={"type": "task", "source": "agent"}).json()
    assert client.get("/api/agent/runs").json()[0]["status"] == "completed"


def test_empty_and_rejected_mission(monkeypatch):
    monkeypatch.setattr(stub_server, "events", [])
    monkeypatch.setattr(stub_server, "tasks", [])
    monkeypatch.setattr(stub_server, "mission", None)
    client = TestClient(stub_server.app)
    result = agent.simulate_mission("check", "http://testserver", client)
    assert result["bays"] == agent.BAYS
    assert client.get("/api/tasks").json() == []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=[] if request.url.path != "/api/drone/state" else {})
        assert request.url.path == "/api/drone/mission"
        return httpx.Response(200, json={"accepted": False, "rejected_reason": "battery"})
    rejected = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="battery"):
        agent.simulate_mission("check", "http://test", rejected)


def test_mock_failure_recorded(monkeypatch):
    monkeypatch.setenv("SENTINEL_AGENT_MOCK", "1")
    def fail(goal, base):
        raise RuntimeError("offline")
    monkeypatch.setattr(agent, "simulate_mission", fail)
    run = agent.launch("check", "http://localhost")
    result = agent.wait(run["session_id"])
    assert result["status"] == "failed" and result["error"] == "offline"
