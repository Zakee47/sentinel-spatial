"""Tiny stand-in for the W1 server's drone endpoints (stdlib only), for running drone/ alone.

    python -m drone.devserver --port 8000
    curl -X POST localhost:8000/api/drone/mission -d '{"bays":["bay-B-01","bay-B-02"],"reason":"test","requested_by":"user"}'
    curl -X POST localhost:8000/api/drone/stop

Implements: GET/POST /api/drone/state, POST /api/drone/stop, GET/POST /api/drone/mission,
POST /api/events, POST /api/tasks, GET /api/events, GET /api/tasks. In-memory only.
"""

from __future__ import annotations

import argparse
import json
import threading
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class Store:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state: dict[str, Any] = {"state": "IDLE", "stop_requested": False, "mission_id": None}
        self.mission: dict[str, Any] | None = None
        self.events: list[dict[str, Any]] = []
        self.tasks: list[dict[str, Any]] = []


def make_handler(store: Store) -> type[BaseHTTPRequestHandler]:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:
            pass

        def _json(self, obj: Any, code: int = 200) -> None:
            raw = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _body(self) -> Any:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"null")

        def do_GET(self) -> None:
            path = self.path.split("?")[0]
            with store.lock:
                if path == "/api/health":
                    return self._json({"ok": True})
                if path == "/api/drone/state":
                    return self._json(store.state)
                if path == "/api/drone/mission":
                    return self._json(store.mission)
                if path == "/api/events":
                    return self._json(list(reversed(store.events)))
                if path == "/api/tasks":
                    return self._json(store.tasks)
            self._json({"detail": "not found"}, 404)

        def do_POST(self) -> None:
            path, body = self.path.split("?")[0], self._body()
            with store.lock:
                if path == "/api/drone/state":
                    stop = store.state.get("stop_requested", False)
                    store.state = {**body, "stop_requested": stop or bool(body.get("stop_requested"))}
                    if store.mission and body.get("state") == "IDLE" and store.state.get("_seen_active"):
                        store.mission = None  # mission finished
                    if body.get("mission_id"):
                        store.state["_seen_active"] = True
                    elif body.get("state") == "IDLE":
                        store.state.pop("_seen_active", None)
                    return self._json({"ok": True})
                if path == "/api/drone/stop":
                    store.state["stop_requested"] = True
                    return self._json({"ok": True})
                if path == "/api/drone/mission":
                    mid = "m-" + uuid.uuid4().hex[:8]
                    store.mission = {**body, "mission_id": mid, "status": "pending"}
                    return self._json({"accepted": True, "mission_id": mid})
                if path == "/api/events":
                    items = body if isinstance(body, list) else [body]
                    ids = []
                    for e in items:
                        e = {**e, "event_id": e.get("event_id") or uuid.uuid4().hex,
                             "ts": e.get("ts") or datetime.now(UTC).isoformat()}
                        store.events.append(e)
                        ids.append(e["event_id"])
                    return self._json({"inserted": len(ids), "event_ids": ids})
                if path == "/api/tasks":
                    t = {"task_id": "T-" + uuid.uuid4().hex[:6], "created_at": datetime.now(UTC).isoformat(),
                         "status": "open", "assignee": None, **body}
                    store.tasks.append(t)
                    return self._json(t)
            self._json({"detail": "not found"}, 404)

    return H


def serve(port: int = 8000, store: Store | None = None) -> tuple[ThreadingHTTPServer, Store]:
    store = store or Store()
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, store


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(Store()))
    print(f"drone devserver on http://127.0.0.1:{a.port}")
    srv.serve_forever()
