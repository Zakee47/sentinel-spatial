"""Network side (runs in its own thread, NEVER inside the flight loop).

`Link` polls GET /api/drone/state (stop_requested) and GET /api/drone/mission, pushes
DroneState at >= 2 Hz, and drains the patrol's outbox (events, tasks). The flight loop only
reads `Link.snapshot()` and appends to the outbox.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("drone.api")


class ApiClient:
    def __init__(self, base: str, timeout_s: float = 1.5) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout_s

    def _req(self, method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else None

    def get(self, path: str) -> Any:
        return self._req("GET", path)

    def post(self, path: str, body: Any) -> Any:
        return self._req("POST", path, body)


@dataclass
class LinkSnapshot:
    stop_requested: bool = False
    mission: dict[str, Any] | None = None
    link_up: bool = False
    link_down_s: float = 0.0  # seconds since the link was last up (0 if never up)
    people_xy: list[tuple[float, float]] = field(default_factory=list)


class Link:
    def __init__(self, client: ApiClient | None, state_hz: float = 3.0) -> None:
        self.client = client
        self.state_period = 1.0 / state_hz
        self.outbox: queue.Queue[dict[str, Any]] = queue.Queue()
        self._snap = LinkSnapshot()
        self._lock = threading.Lock()
        self._state: dict[str, Any] | None = None
        self._stop = threading.Event()
        self._last_up: float | None = None
        self._thread = threading.Thread(target=self._run, name="drone-link", daemon=True)
        self.sent: list[dict[str, Any]] = []  # everything we tried to send (for logs/tests)

    # called from the flight loop (cheap, non-blocking)
    def snapshot(self) -> LinkSnapshot:
        with self._lock:
            s = self._snap
            down = 0.0 if self._last_up is None or s.link_up else time.monotonic() - self._last_up
            return LinkSnapshot(s.stop_requested, s.mission, s.link_up, down, list(s.people_xy))

    def publish_state(self, state: dict[str, Any]) -> None:
        with self._lock:
            self._state = state

    def inject_mission(self, mission: dict[str, Any]) -> None:
        with self._lock:
            self._snap.mission = mission

    def set_people(self, people_xy: list[tuple[float, float]]) -> None:
        with self._lock:
            self._snap.people_xy = people_xy

    def request_stop(self) -> None:
        with self._lock:
            self._snap.stop_requested = True

    def start(self) -> None:
        self._thread.start()

    def close(self, flush_s: float = 3.0) -> None:
        deadline = time.monotonic() + flush_s
        while not self.outbox.empty() and time.monotonic() < deadline:
            time.sleep(0.05)
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    # network thread
    def _run(self) -> None:
        next_state = next_poll = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_state:
                next_state = now + self.state_period
                with self._lock:
                    st = self._state
                if st is not None:
                    self._send("POST", "/api/drone/state", st, record=False)
            if now >= next_poll:
                next_poll = now + 0.5
                self._poll()
            try:
                item = self.outbox.get(timeout=0.05)
            except queue.Empty:
                continue
            self._deliver(item)

    def _poll(self) -> None:
        if self.client is None:
            return
        try:
            state = self.client.get("/api/drone/state") or {}
            mission = self.client.get("/api/drone/mission")
        except (urllib.error.URLError, OSError, ValueError) as e:
            self._mark(False)
            log.debug("poll failed: %s", e)
            return
        self._mark(True)
        with self._lock:
            self._snap.stop_requested = self._snap.stop_requested or bool(state.get("stop_requested"))
            if mission:
                self._snap.mission = mission

    def _mark(self, up: bool) -> None:
        with self._lock:
            self._snap.link_up = up
            if up:
                self._last_up = time.monotonic()

    def _send(self, method: str, path: str, body: Any, record: bool = True) -> Any:
        if record:
            self.sent.append({"path": path, "body": body})
        if self.client is None:
            return None
        try:
            return self.client._req(method, path, body)
        except (urllib.error.URLError, OSError, ValueError) as e:
            log.warning("%s %s failed: %s", method, path, e)
            return None

    def _deliver(self, item: dict[str, Any]) -> None:
        """item = {"event": Event, "task": Task-body|None}; task.source_event = new event id."""
        res = self._send("POST", "/api/events", item["event"])
        task = item.get("task")
        if task:
            ids = (res or {}).get("event_ids") or [None]
            self._send("POST", "/api/tasks", {**task, "source_event": ids[0]})
