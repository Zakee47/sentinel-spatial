"""DroneDriver interface shared by every drone backend.

Implementations:
- ``SimDriver`` (drone/sim.py): kinematic simulator in the twin frame + synthetic bay images.
- ``LiveFeedDriver`` (drone/live.py): live DJI Neo 2 *video only*; a human pilots the drone.
- ``NeoDriver`` / ``TelloDriver`` (drone/live.py): stubs, see docs/rea/.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

FixSource = Literal["sim", "portal", "estimate", "none"]


class NotSupported(RuntimeError):
    """Raised by drivers that cannot fly from code (e.g. the live Neo 2 feed: the human pilots)."""


@dataclass
class Telemetry:
    ts: float
    x: float
    y: float
    z: float
    yaw_deg: float
    battery_pct: float
    has_fix: bool
    fix_source: FixSource
    airborne: bool
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    last_fix_ts: float = 0.0  # monotonic time of the last good position fix


@dataclass
class Frame:
    ts: float
    image: np.ndarray  # BGR uint8, HxWx3
    source: str = "sim"  # "sim" | "live"
    bay_id: str | None = None  # bay the frame was taken at (sim only)
    meta: dict = field(default_factory=dict)  # e.g. {"truth": "empty"} for sim frames

    def jpeg(self, quality: int = 85) -> bytes:
        import cv2

        ok, buf = cv2.imencode(".jpg", self.image, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            raise RuntimeError("JPEG encode failed")
        return buf.tobytes()


class DroneDriver(ABC):
    mode: str = "sim"
    feed_url: str | None = None

    @abstractmethod
    def takeoff(self) -> None: ...

    @abstractmethod
    def land(self) -> None: ...

    @abstractmethod
    def send_velocity(self, vx: float, vy: float, vz: float, yaw_rate: float) -> None:
        """Twin-frame velocity setpoint in m/s (yaw_rate in deg/s). Must already be supervised."""

    @abstractmethod
    def video_frames(self) -> Iterator[Frame]: ...

    @abstractmethod
    def telemetry(self) -> Telemetry: ...

    def latest_frame(self) -> Frame | None:
        """Non-blocking: most recent frame (default pulls one from video_frames())."""
        return next(iter(self.video_frames()), None)

    def step(self, dt: float) -> None:
        """Advance simulated physics by dt seconds (no-op for real drivers)."""

    def close(self) -> None:
        """Release resources."""


def now() -> float:
    return time.monotonic()
