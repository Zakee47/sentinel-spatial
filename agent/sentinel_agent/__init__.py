"""Launch and track Sentinel mission-planning sessions."""

from __future__ import annotations

import fcntl
import json
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parent.parent
BAYS = [f"bay-B-{i:02d}" for i in range(1, 5)]
_threads: dict[str, threading.Thread] = {}


class DevinAPIError(RuntimeError):
    """A Devin API request failed."""


def _runs_path() -> Path:
    return Path(os.environ.get("SENTINEL_AGENT_RUNS", str(ROOT / ".runs.json")))


def _store(update: dict | None = None) -> list[dict]:
    path = _runs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        runs = json.loads(path.read_text()) if path.exists() else []
        if update is not None:
            for i, run in enumerate(runs):
                if run["session_id"] == update["session_id"]:
                    runs[i] = {**run, **update}
                    break
            else:
                runs.append(update)
            temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                temp.write_text(json.dumps(runs, indent=2))
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
        return runs


def list_runs() -> list[dict]:
    return _store()


DEFAULT_ORG_ID = "org-3e3903fc352442af8b96c7a5098f0774"


def is_mock() -> bool:
    return os.environ.get("SENTINEL_AGENT_MOCK", "1") != "0"


def _api_config() -> tuple[str, str, str]:
    key = os.environ.get("DEVIN_API_KEY", "")
    if not key:
        raise DevinAPIError("DEVIN_API_KEY is required")
    version = os.environ.get("DEVIN_API_VERSION", "v3" if key.startswith("cog_") else "v1")
    if version not in ("v1", "v3"):
        raise DevinAPIError("DEVIN_API_VERSION must be v1 or v3")
    base = os.environ.get("DEVIN_API_BASE", "https://api.devin.ai").rstrip("/")
    if version == "v3":
        org = os.environ.get("DEVIN_ORG_ID") or DEFAULT_ORG_ID
        base += f"/v3/organizations/{quote(org, safe='')}/sessions"
    else:
        base += "/v1/sessions"
    return version, base, key


def _request(method: str, url: str, key: str, **kwargs: object) -> dict:
    response = httpx.request(method, url, headers={"Authorization": f"Bearer {key}"},
                             timeout=30, **kwargs)
    if response.is_error:
        try:
            body = response.json()
            detail = body.get("detail", body) if isinstance(body, dict) else body
        except ValueError:
            detail = response.text
        raise DevinAPIError(f"Devin API HTTP {response.status_code}: {detail}")
    return response.json()


def launch(goal: str, api_base: str) -> dict:
    if not goal.strip() or not api_base.strip():
        raise ValueError("goal and api_base must not be empty")
    mock = is_mock()
    if mock:
        session_id = "mock-" + uuid.uuid4().hex
        url = f"https://app.devin.ai/sessions/{session_id}"
    else:
        version, endpoint, key = _api_config()
        prompt = (ROOT / "prompts" / "mission.md").read_text().format(
            goal=goal, api_base=api_base.rstrip("/"))
        body = {"prompt": prompt, "title": "Sentinel mission: " + goal,
                "tags": ["sentinel", "mission"]}
        if version == "v3":
            body["structured_output_schema"] = json.loads(
                (ROOT / "prompts" / "plan_schema.json").read_text())
        result = _request("POST", endpoint, key, json=body)
        session_id, url = result["session_id"], result["url"]
    run = {"session_id": session_id, "url": url, "goal": goal,
           "status": "running", "created_at": datetime.now(UTC).isoformat()}
    _store(run)
    if mock:
        thread = threading.Thread(target=_run_mock, args=(session_id, goal, api_base), daemon=True)
        _threads[session_id] = thread
        thread.start()
    return run


def status(session_id: str) -> dict:
    run = next((r for r in list_runs() if r["session_id"] == session_id), None)
    if run is None:
        raise KeyError(f"Unknown session: {session_id}")
    if not session_id.startswith("mock-"):
        version, endpoint, key = _api_config()
        if version == "v1":
            endpoint = endpoint.removesuffix("sessions") + "session"
        result = _request("GET", f"{endpoint}/{quote(session_id, safe='')}", key)
        run["status"] = result.get("status_enum") or result.get("status") or run["status"]
        _store(run)
    return run


def wait(session_id: str) -> dict:
    thread = _threads.get(session_id)
    if thread:
        thread.join()
    return status(session_id)


def simulate_mission(goal: str, api_base: str, client: httpx.Client | None = None) -> dict:
    """Synchronously run the mock planner, optionally with an injected HTTP client."""
    own_client = client is None
    client = client or httpx.Client(base_url=api_base.rstrip("/"), timeout=30)
    try:
        def get(path: str) -> object:
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        def post(path: str, data: dict) -> dict:
            response = client.post(path, json=data)
            response.raise_for_status()
            return response.json()

        events = get("/api/events")
        get("/api/tasks")
        get("/api/drone/state")
        get("/api/funnel")
        flagged = [e for e in events if e.get("type") == "bay_issue"
                   and e.get("zone_id") in BAYS]
        flagged_bays = list(dict.fromkeys(e["zone_id"] for e in flagged))
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        recent = set()
        for event in events:
            try:
                ts = datetime.fromisoformat(event.get("ts", ""))
                if ts.tzinfo and ts >= cutoff:
                    recent.add(event.get("zone_id"))
            except (ValueError, TypeError):
                pass
        bays = flagged_bays + [bay for bay in BAYS if bay not in recent and bay not in flagged_bays]
        bays = bays or BAYS.copy()
        reason = f"{goal}: inspect flagged or stale bays"
        mission = post("/api/drone/mission", {"bays": bays, "reason": reason,
                                              "requested_by": "agent"})
        if not mission.get("accepted"):
            raise RuntimeError(f"Mission rejected: {mission.get('rejected_reason', 'unknown reason')}")
        for event in flagged:
            payload = event.get("payload") or {}
            post("/api/tasks", {"zone_id": event["zone_id"],
                 "kind": payload.get("issue", "inspection"),
                 "severity": payload.get("severity", "act_today"),
                 "source_event": event.get("event_id"), "note": f"Review bay issue for {goal}"})
        summary = f"{goal}: mission queued for {', '.join(bays)}; {len(flagged)} flagged issues."
        post("/api/events", {"site_id": "demo-warehouse", "zone_id": bays[0],
             "type": "task", "source": "agent", "payload": {"summary": summary}})
        return {"bays": bays, "mission": mission, "summary": summary}
    finally:
        if own_client:
            client.close()


def _run_mock(session_id: str, goal: str, api_base: str) -> None:
    try:
        simulate_mission(goal, api_base)
        update = {"session_id": session_id, "status": "completed"}
    except Exception as exc:  # noqa: BLE001
        update = {"session_id": session_id, "status": "failed", "error": str(exc)}
    _store(update)
