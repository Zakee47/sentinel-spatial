"""Robust, low-latency OpenCV capture for CCTV sources.

Supports rtsp:// rtsps:// http(s) MJPEG, HLS .m3u8, rtmp://, files and device indexes.
A background thread keeps grabbing so `read()` always returns the newest frame
(stale frames are dropped); the stream auto-reconnects with exponential backoff.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self
from urllib.parse import quote, urlsplit, urlunsplit

FFMPEG_OPTS = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|stimeout;5000000|max_delay;500000"
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", FFMPEG_OPTS)

import cv2
import numpy as np

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


@dataclass(frozen=True)
class SourceInfo:
    kind: str  # rtsp | http_mjpeg | hls | rtmp | http | file | device
    uri: str | int
    live: bool

    @property
    def redacted(self) -> str:
        return redact(str(self.uri))


def expand_env(uri: str) -> str:
    """Replace ${VAR} placeholders (e.g. credentials) from the environment."""
    return _ENV_RE.sub(lambda m: quote(os.environ.get(m.group(1), ""), safe=""), uri)


def redact(uri: str) -> str:
    p = urlsplit(uri)
    if p.password is None and p.username is None:
        return uri
    host = p.hostname or ""
    if p.port:
        host += f":{p.port}"
    return urlunsplit((p.scheme, f"***@{host}", p.path, p.query, p.fragment))


def parse_uri(uri: str | int) -> SourceInfo:
    if isinstance(uri, int) or (isinstance(uri, str) and uri.strip().isdigit()):
        return SourceInfo("device", int(uri), True)
    u = expand_env(uri.strip())
    scheme = urlsplit(u).scheme.lower()
    path = urlsplit(u).path.lower()
    if scheme in ("rtsp", "rtsps"):
        return SourceInfo("rtsp", u, True)
    if scheme in ("rtmp", "rtmps"):
        return SourceInfo("rtmp", u, True)
    if scheme in ("http", "https"):
        if path.endswith(".m3u8"):
            return SourceInfo("hls", u, True)
        if "mjpg" in u.lower() or "mjpeg" in u.lower() or path.endswith((".cgi", "/video")):
            return SourceInfo("http_mjpeg", u, True)
        return SourceInfo("http", u, not path.endswith((".mp4", ".mkv", ".avi", ".mov")))
    if scheme == "file":
        u = urlsplit(u).path
    return SourceInfo("file", str(Path(u).expanduser()), False)


@dataclass
class Backoff:
    initial: float = 0.5
    factor: float = 2.0
    maximum: float = 30.0
    attempt: int = 0

    def next_delay(self) -> float:
        d = min(self.maximum, self.initial * (self.factor**self.attempt))
        self.attempt += 1
        return d

    def reset(self) -> None:
        self.attempt = 0


@dataclass
class Health:
    connected: bool = False
    frames: int = 0
    dropped: int = 0
    reconnects: int = 0
    fps: float = 0.0
    last_frame_ts: float | None = None
    last_error: str | None = None
    width: int = 0
    height: int = 0
    _fps_window: list[float] = field(default_factory=list, repr=False)

    def on_frame(self, now: float) -> None:
        self.frames += 1
        self.last_frame_ts = now
        self._fps_window.append(now)
        cutoff = now - 2.0
        while self._fps_window and self._fps_window[0] < cutoff:
            self._fps_window.pop(0)
        if len(self._fps_window) > 1:
            span = self._fps_window[-1] - self._fps_window[0]
            self.fps = (len(self._fps_window) - 1) / span if span > 0 else 0.0

    def as_dict(self, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        age = None if self.last_frame_ts is None else round(now - self.last_frame_ts, 3)
        return {
            "connected": self.connected,
            "frames": self.frames,
            "dropped": self.dropped,
            "reconnects": self.reconnects,
            "fps": round(self.fps, 2),
            "last_frame_age_s": age,
            "width": self.width,
            "height": self.height,
            "last_error": self.last_error,
        }


def _open_capture(info: SourceInfo) -> cv2.VideoCapture:
    if info.kind == "device":
        cap = cv2.VideoCapture(info.uri)
    else:
        cap = cv2.VideoCapture(str(info.uri), cv2.CAP_FFMPEG)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except cv2.error:
        pass
    return cap


class CCTVSource:
    """Threaded latest-frame reader. `read()` mirrors cv2.VideoCapture.read()."""

    def __init__(
        self,
        uri: str | int,
        *,
        backoff: Backoff | None = None,
        loop_files: bool = False,
        stale_after_s: float = 5.0,
        opener: Any = _open_capture,
    ) -> None:
        self.info = parse_uri(uri)
        self.backoff = backoff or Backoff()
        self.loop_files = loop_files
        self.stale_after_s = stale_after_s
        self.health = Health()
        self._opener = opener
        self._lock = threading.Lock()
        self._new = threading.Condition(self._lock)
        self._frame: np.ndarray | None = None
        self._seq = 0
        self._read_seq = 0
        self._stop = threading.Event()
        self._eof = False
        self._file_fps = 0.0
        self._thread = threading.Thread(target=self._run, name=f"cctv:{self.info.redacted}", daemon=True)
        self._thread.start()

    # --- public API -----------------------------------------------------------------
    def read(self, timeout: float = 10.0) -> tuple[bool, np.ndarray | None]:
        """Block until a frame newer than the last one read is available."""
        deadline = time.time() + timeout
        with self._new:
            while self._seq == self._read_seq and not self._stop.is_set():
                if self._eof:
                    return False, None
                left = deadline - time.time()
                if left <= 0:
                    return False, None
                self._new.wait(left)
            if self._frame is None:
                return False, None
            self._read_seq = self._seq
            return True, self._frame.copy()

    def latest(self) -> np.ndarray | None:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def is_stale(self) -> bool:
        ts = self.health.last_frame_ts
        return ts is None or time.time() - ts > self.stale_after_s

    def isOpened(self) -> bool:
        return not self._stop.is_set() and not self._eof

    def get(self, prop: int) -> float:
        if prop == cv2.CAP_PROP_FPS:
            return self._file_fps or self.health.fps
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self.health.width)
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self.health.height)
        return 0.0

    def release(self) -> None:
        self._stop.set()
        with self._new:
            self._new.notify_all()
        self._thread.join(timeout=3)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()

    # --- worker ---------------------------------------------------------------------
    def _publish(self, frame: np.ndarray) -> None:
        now = time.time()
        with self._new:
            if self._seq != self._read_seq:
                self.health.dropped += 1
            self._frame = frame
            self._seq += 1
            self.health.on_frame(now)
            self.health.height, self.health.width = frame.shape[:2]
            self._new.notify_all()

    def _run(self) -> None:
        while not self._stop.is_set():
            cap = self._opener(self.info)
            if not cap.isOpened():
                self.health.connected = False
                self.health.last_error = "open failed"
                if not self.info.live and not self.loop_files:
                    self._finish()
                    return
                self._sleep_backoff()
                continue
            self.health.connected = True
            self.health.last_error = None
            self.backoff.reset()
            self._file_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) if not self.info.live else 0.0
            period = 1.0 / self._file_fps if self._file_fps > 0 else 0.0
            while not self._stop.is_set():
                t0 = time.time()
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                self._publish(frame)
                if period:  # pace files at native fps so they behave like a live camera
                    time.sleep(max(0.0, period - (time.time() - t0)))
            cap.release()
            self.health.connected = False
            if self._stop.is_set():
                return
            if not self.info.live and not self.loop_files:
                self._finish()
                return
            self.health.last_error = "stream ended"
            self.health.reconnects += 1
            self._sleep_backoff()

    def _sleep_backoff(self) -> None:
        self._stop.wait(self.backoff.next_delay())

    def _finish(self) -> None:
        with self._new:
            self._eof = True
            self._new.notify_all()


def open_source(uri: str | int, **kwargs: Any) -> CCTVSource:
    """Open a CCTV/OpenCV source with TCP transport, latest-frame reads and auto-reconnect."""
    return CCTVSource(uri, **kwargs)


def load_cameras(path: str | Path | None = None) -> dict[str, str]:
    """camera id -> URI from cameras.local.yaml (gitignored) or cameras.example.yaml."""
    import yaml

    here = Path(__file__).resolve().parent
    candidates = [Path(path)] if path else [here / "cameras.local.yaml", here / "cameras.example.yaml"]
    for p in candidates:
        if p.exists():
            data = yaml.safe_load(p.read_text()) or {}
            return {str(c["id"]): str(c["uri"]) for c in data.get("cameras", [])}
    return {}
