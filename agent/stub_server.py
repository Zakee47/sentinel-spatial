"""In-memory Sentinel API for exercising the mission agent locally."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, Request
from pydantic import BaseModel

from agent import sentinel_agent

app = FastAPI()
events: list[dict] = [
    {"event_id": "seed-1", "ts": "2026-01-01T00:00:00Z", "site_id": "demo-warehouse",
     "zone_id": "bay-B-01", "type": "bay_issue", "source": "drone-1",
     "payload": {"issue": "empty", "severity": "act_now"}},
    {"event_id": "seed-2", "ts": "2026-01-01T00:00:00Z", "site_id": "demo-warehouse",
     "zone_id": "bay-B-02", "type": "bay_issue", "source": "drone-1",
     "payload": {"issue": "misplaced", "severity": "act_today"}},
]
tasks: list[dict] = []
mission: dict | None = None


def now() -> str:
    return datetime.now(UTC).isoformat()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/events")
def get_events(type: str | None = None, zone_id: str | None = None,
               source: str | None = None, since: str | None = None, limit: int = 200) -> list[dict]:
    return [e for e in reversed(events) if (not type or e.get("type") == type)
            and (not zone_id or e.get("zone_id") == zone_id)
            and (not source or e.get("source") == source)
            and (not since or e.get("ts", "") >= since)][:limit]


@app.post("/api/events")
def post_events(body: dict | list[dict]) -> dict:
    items = body if isinstance(body, list) else [body]
    ids = []
    for item in items:
        event = {"event_id": uuid4().hex, "ts": now(), **item}
        events.append(event)
        ids.append(event["event_id"])
    return {"inserted": len(ids), "event_ids": ids}


@app.get("/api/tasks")
def get_tasks(status: str | None = None) -> list[dict]:
    return [task for task in tasks if not status or task["status"] == status]


@app.post("/api/tasks")
def post_task(body: dict) -> dict:
    task = {"task_id": uuid4().hex, "created_at": now(), "status": "open",
            "source_event": None, "assignee": None, "note": None, **body}
    tasks.append(task)
    return task


@app.get("/api/drone/state")
def drone_state() -> dict:
    return {"ts": now(), "mode": "sim", "state": "IDLE", "x": 0, "y": 0, "z": 0,
            "yaw_deg": 0, "battery_pct": 100, "current_bay": None, "last_decision": None,
            "stop_requested": False, "mission_id": None, "feed_url": None}


@app.get("/api/funnel")
def funnel() -> list[dict]:
    return []


@app.post("/api/drone/mission")
def post_mission(body: dict) -> dict:
    global mission
    mission_id = uuid4().hex
    mission = {"mission_id": mission_id, **body}
    return {"accepted": True, "mission_id": mission_id}


@app.get("/api/drone/mission")
def get_mission() -> dict | None:
    return mission


class RunRequest(BaseModel):
    goal: str


@app.post("/api/agent/run")
def agent_run(body: RunRequest, request: Request) -> dict:
    run = sentinel_agent.launch(body.goal, str(request.base_url).rstrip("/"))
    return {"session_id": run["session_id"], "url": run["url"]}


@app.get("/api/agent/runs")
def agent_runs() -> list[dict]:
    return sentinel_agent.list_runs()
