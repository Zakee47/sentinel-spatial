"""Event sink: POST to SENTINEL_API/api/events, always mirrored to perception/out/events.jsonl."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import requests


class EventSink:
    def __init__(self, out_path: Path, api: str | None = None, post: bool = True):
        self.api = (api or os.environ.get("SENTINEL_API", "http://localhost:8000")).rstrip("/")
        self.out_path = out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(out_path, "w")  # noqa: SIM115
        self.post_enabled = post
        self.server_ok: bool | None = None
        self.count = 0

    def emit(self, ev: dict) -> None:
        ev.setdefault("ts", datetime.now(UTC).isoformat().replace("+00:00", "Z"))
        self.f.write(json.dumps(ev) + "\n")
        self.f.flush()
        self.count += 1
        if self.post_enabled and self.server_ok is not False:
            try:
                r = requests.post(f"{self.api}/api/events", json=ev, timeout=1.5)
                self.server_ok = r.ok
            except requests.RequestException:
                self.server_ok = False  # server down: keep writing jsonl only
        print(f"[event] {ev['type']:<9} zone={ev.get('zone_id')} track={ev.get('track_id')} "
              f"prod={ev.get('product_id')} conf={ev.get('confidence')} {ev.get('payload')}", flush=True)

    def close(self) -> None:
        self.f.close()
