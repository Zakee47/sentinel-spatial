from __future__ import annotations

import time

import numpy as np
import pytest

from cctv import sources
from cctv.onvif_discover import build_probe, parse_probe_match
from cctv.run_perception import build_argv
from cctv.sources import Backoff, CCTVSource, expand_env, parse_uri, redact


@pytest.mark.parametrize(
    ("uri", "kind", "live"),
    [
        ("rtsp://cam/Streaming/Channels/101", "rtsp", True),
        ("rtsps://cam:322/stream1", "rtsp", True),
        ("http://10.0.0.5/video.mjpg", "http_mjpeg", True),
        ("http://10.0.0.5/cgi-bin/mjpg/video.cgi", "http_mjpeg", True),
        ("https://cdn.example/live/index.m3u8", "hls", True),
        ("rtmp://localhost/live/drone", "rtmp", True),
        ("http://example.com/clip.mp4", "http", False),
        ("perception/footage/aisle.mp4", "file", False),
        ("0", "device", True),
        (2, "device", True),
    ],
)
def test_parse_uri(uri, kind, live):
    info = parse_uri(uri)
    assert (info.kind, info.live) == (kind, live)


def test_env_credentials_expanded_and_redacted(monkeypatch):
    monkeypatch.setenv("CAM_USER", "admin")
    monkeypatch.setenv("CAM_PASS", "p@ss:w/rd")
    info = parse_uri("rtsp://${CAM_USER}:${CAM_PASS}@192.168.1.64:554/Streaming/Channels/101")
    assert info.uri == "rtsp://admin:p%40ss%3Aw%2Frd@192.168.1.64:554/Streaming/Channels/101"
    assert info.redacted == "rtsp://***@192.168.1.64:554/Streaming/Channels/101"
    assert "p%40ss" not in info.redacted
    assert expand_env("rtsp://x/${MISSING_VAR_XYZ}") == "rtsp://x/"


def test_redact_noop_without_creds():
    assert redact("rtsp://cam/stream") == "rtsp://cam/stream"


def test_backoff_exponential_capped_and_reset():
    b = Backoff(initial=0.5, factor=2.0, maximum=4.0)
    assert [b.next_delay() for _ in range(6)] == [0.5, 1.0, 2.0, 4.0, 4.0, 4.0]
    b.reset()
    assert b.next_delay() == 0.5


class FakeCap:
    def __init__(self, n_frames: int, opened: bool = True):
        self.n, self.opened, self.released = n_frames, opened, False

    def isOpened(self):
        return self.opened

    def read(self):
        if self.n <= 0:
            return False, None
        self.n -= 1
        time.sleep(0.005)
        return True, np.full((4, 6, 3), self.n, np.uint8)

    def get(self, prop):
        return 0.0

    def release(self):
        self.released = True


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_reconnects_after_open_failures_and_stream_drop():
    caps = [FakeCap(0, opened=False), FakeCap(0, opened=False), FakeCap(3), FakeCap(5)]
    opened = []

    def opener(info):
        c = caps.pop(0) if caps else FakeCap(0, opened=False)
        opened.append(c)
        return c

    src = CCTVSource("rtsp://cam/x", backoff=Backoff(initial=0.01, maximum=0.02), opener=opener)
    try:
        assert wait_for(lambda: src.health.frames >= 8)
        assert src.health.reconnects >= 1
        _ok, frame = src.read(timeout=1)
        assert frame is None or frame.shape == (4, 6, 3)
        assert src.get(sources.cv2.CAP_PROP_FRAME_WIDTH) == 6
        assert all(c.released for c in opened if c.opened)
    finally:
        src.release()


def test_file_source_ends_without_loop():
    src = CCTVSource("clip.mp4", opener=lambda info: FakeCap(2))
    try:
        frames = 0
        while True:
            ok, _ = src.read(timeout=1)
            if not ok:
                break
            frames += 1
        assert 1 <= frames <= 2
        assert not src.isOpened()
    finally:
        src.release()


def test_latest_frame_drops_stale():
    src = CCTVSource("rtsp://cam/x", opener=lambda info: FakeCap(50), backoff=Backoff(initial=10))
    try:
        assert wait_for(lambda: src.health.frames >= 50)
        ok, frame = src.read(timeout=0.2)
        assert ok and int(frame[0, 0, 0]) == 0  # newest frame, not the first
        assert src.health.dropped > 0
        assert src.health.as_dict()["last_frame_age_s"] is not None
    finally:
        src.release()


def test_onvif_probe_and_match_parse():
    assert b"NetworkVideoTransmitter" in build_probe("abc")
    xml = (
        "<d:ProbeMatch><d:Scopes>onvif://www.onvif.org/name/HIKVISION%20DS-2CD "
        "onvif://www.onvif.org/hardware/DS-2CD2143</d:Scopes>"
        "<d:XAddrs>http://192.168.1.64/onvif/device_service</d:XAddrs></d:ProbeMatch>"
    )
    m = parse_probe_match(xml)
    assert m["xaddrs"] == ["http://192.168.1.64/onvif/device_service"]
    assert m["name"] == "HIKVISION DS-2CD"
    assert m["hardware"] == "DS-2CD2143"


def test_run_perception_argv():
    argv = build_argv("camera-1", "rtsp://localhost:8554/camera-1", ["--mock"])
    assert argv[1:] == ["-m", "perception.run", "--source", "rtsp://localhost:8554/camera-1", "--camera", "camera-1", "--mock"]
