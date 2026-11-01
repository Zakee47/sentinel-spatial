"""Link against the stdlib devserver: state push, mission poll, STOP, events -> tasks."""

import socket
import time

from drone.api import ApiClient, Link
from drone.devserver import serve


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait(cond, timeout=3.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_link_roundtrip():
    port = free_port()
    srv, store = serve(port)
    client = ApiClient(f"http://127.0.0.1:{port}")
    link = Link(client, state_hz=5)
    link.start()
    try:
        client.post("/api/drone/mission", {"bays": ["bay-B-02"], "reason": "t", "requested_by": "user"})
        assert wait(lambda: (link.snapshot().mission or {}).get("bays") == ["bay-B-02"])
        link.publish_state({"state": "GOTO_BAY", "x": 1.0, "mission_id": "m"})
        assert wait(lambda: store.state.get("state") == "GOTO_BAY")
        link.outbox.put({"event": {"type": "bay_issue", "zone_id": "bay-B-02"},
                         "task": {"zone_id": "bay-B-02", "kind": "restock", "severity": 2.0, "note": "x"}})
        assert wait(lambda: len(store.tasks) == 1)
        assert store.tasks[0]["source_event"] == store.events[0]["event_id"]
        client.post("/api/drone/stop", {})
        assert wait(lambda: link.snapshot().stop_requested)
    finally:
        link.close()
        srv.shutdown()


def test_link_offline_counts_down():
    link = Link(None)
    assert link.snapshot().link_down_s == 0.0 and not link.snapshot().stop_requested
