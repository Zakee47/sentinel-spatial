"""SimDriver: kinematic drone simulator in the twin frame with synthetic bay images.

Bay ground truth for the demo: bay-B-02 has an empty pick face, bay-B-03 a misplaced carton.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import cv2
import numpy as np

from drone.driver import DroneDriver, Frame, Telemetry
from drone.site import bay_centre, bays, inspect_point

BAY_TRUTH: dict[str, str] = {"bay-B-01": "ok", "bay-B-02": "empty", "bay-B-03": "misplaced", "bay-B-04": "ok"}
IMG_W, IMG_H = 640, 480


def render_bay(bay_id: str, truth: str = "ok", seed: int = 0, offset_px: tuple[int, int] = (0, 0)) -> np.ndarray:
    """Draw a synthetic pallet-rack bay: 3 beam levels, 3 pick faces per level, cartons."""
    rng = np.random.default_rng(seed + sum(map(ord, bay_id)))
    img = np.full((IMG_H, IMG_W, 3), (58, 58, 62), np.uint8)
    cv2.rectangle(img, (0, 420), (IMG_W, IMG_H), (90, 96, 100), -1)  # floor
    ox, oy = offset_px
    left, right, top, bottom = 60 + ox, 580 + ox, 30 + oy, 430 + oy
    levels = [bottom, 300 + oy, 170 + oy, top + 10]
    for x in (left, right):
        cv2.rectangle(img, (x - 10, top), (x + 10, bottom), (0, 110, 230), -1)  # orange uprights
    for y in levels[1:]:
        cv2.rectangle(img, (left, y - 8), (right, y + 4), (170, 90, 20), -1)  # blue beams
    face_w = (right - left) // 3
    for li in range(3):
        y0, y1 = levels[li + 1] + 6, levels[li] - 10
        for fi in range(3):
            x0 = left + 14 + fi * face_w
            if truth == "empty" and li == 0 and fi == 1:
                continue  # empty pick face
            for k in range(2):
                bw = face_w // 2 - 14
                bx = x0 + k * (bw + 6)
                bh = int((y1 - y0) * rng.uniform(0.75, 0.95))
                col = tuple(int(c) for c in (60 + rng.integers(0, 15), 120 + rng.integers(0, 20), 170 + rng.integers(0, 20)))
                cv2.rectangle(img, (bx, y1 - bh), (bx + bw, y1), col, -1)
                cv2.rectangle(img, (bx, y1 - bh), (bx + bw, y1), (40, 80, 110), 2)
                cv2.rectangle(img, (bx + bw // 4, y1 - bh // 2 - 8), (bx + 3 * bw // 4, y1 - bh // 2 + 8),
                              (235, 235, 235), -1)
    if truth == "misplaced":
        # a bright blue tote from another zone, sitting skewed across the mid level
        pts = np.array([[250 + ox, 290 + oy], [370 + ox, 270 + oy], [380 + ox, 210 + oy], [258 + ox, 228 + oy]], np.int32)
        cv2.fillPoly(img, [pts], (200, 120, 30))
        cv2.putText(img, "SKU-014", (268 + ox, 262 + oy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    for y, lab in zip(levels[1:], ("01", "02", "03"), strict=True):
        cv2.rectangle(img, (left + 20, y - 6), (left + 120, y + 4), (240, 240, 240), -1)
        cv2.putText(img, f"{bay_id[-4:]}-{lab}", (left + 24, y + 2), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1)
    noise = rng.normal(0, 6, img.shape).astype(np.int16)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def render_aisle() -> np.ndarray:
    img = np.full((IMG_H, IMG_W, 3), (70, 70, 74), np.uint8)
    cv2.rectangle(img, (0, 300), (IMG_W, IMG_H), (95, 100, 105), -1)
    cv2.putText(img, "aisle (in transit)", (200, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)
    return img


class SimDriver(DroneDriver):
    mode = "sim"

    def __init__(self, site: dict[str, Any], *, clock: Callable[[], float] = time.monotonic,
                 battery_pct: float = 100.0, drain_pct_per_s: float = 0.12, tau_s: float = 0.25,
                 truth: dict[str, str] | None = None) -> None:
        self.site = site
        self.clock = clock
        hx, hy = site["drone"]["home_xy"]
        self.x, self.y, self.z, self.yaw = float(hx), float(hy), 0.0, 90.0
        self.vx = self.vy = self.vz = 0.0
        self.cmd = (0.0, 0.0, 0.0, 0.0)
        self.battery = battery_pct
        self.drain = drain_pct_per_s
        self.tau = tau_s
        self.airborne = False
        self.landing = False
        self.has_fix = True
        self.last_fix_ts = clock()
        self.truth = dict(BAY_TRUTH if truth is None else truth)
        self.commands: list[tuple[float, float, float, float, float]] = []  # (t, vx, vy, vz, yaw_rate)
        self._lock = threading.Lock()
        self._frame_seq = 0

    # --- flight -------------------------------------------------------------------------
    def takeoff(self) -> None:
        self.airborne, self.landing = True, False

    def land(self) -> None:
        self.landing = True

    def send_velocity(self, vx: float, vy: float, vz: float, yaw_rate: float) -> None:
        with self._lock:
            self.cmd = (vx, vy, vz, yaw_rate)
            self.commands.append((self.clock(), vx, vy, vz, yaw_rate))

    def step(self, dt: float) -> None:
        with self._lock:
            vx, vy, vz, yr = self.cmd
            if not self.airborne:
                vx = vy = vz = yr = 0.0
            if self.landing:
                vx = vy = yr = 0.0
                vz = -0.5
            a = min(1.0, dt / self.tau)
            self.vx += (vx - self.vx) * a
            self.vy += (vy - self.vy) * a
            self.vz += (vz - self.vz) * a
            self.x += self.vx * dt
            self.y += self.vy * dt
            self.z = max(0.0, self.z + self.vz * dt)
            self.yaw = (self.yaw + yr * dt) % 360
            if self.landing and self.z <= 0.0:
                self.airborne, self.landing = False, False
                self.vx = self.vy = self.vz = 0.0
            if self.airborne:
                self.battery = max(0.0, self.battery - self.drain * dt)
            if self.has_fix:
                self.last_fix_ts = self.clock()

    def telemetry(self) -> Telemetry:
        with self._lock:
            return Telemetry(ts=self.clock(), x=self.x, y=self.y, z=self.z, yaw_deg=self.yaw,
                             battery_pct=self.battery, has_fix=self.has_fix, fix_source="sim" if self.has_fix else "none",
                             airborne=self.airborne, vx=self.vx, vy=self.vy, vz=self.vz, last_fix_ts=self.last_fix_ts)

    # --- camera -------------------------------------------------------------------------
    def bay_in_view(self, max_dist_m: float = 1.0) -> str | None:
        for bay_id in bays(self.site):
            ix, iy, iz = inspect_point(self.site, bay_id)
            if math.hypot(self.x - ix, self.y - iy) < max_dist_m and abs(self.z - iz) < 1.0:
                return bay_id
        return None

    def latest_frame(self) -> Frame:
        self._frame_seq += 1
        bay_id = self.bay_in_view()
        if bay_id is None:
            return Frame(self.clock(), render_aisle(), "sim", None, {})
        cx, _ = bay_centre(bays(self.site)[bay_id])
        off = (int((cx - self.x) * 120), int((self.z - self.site["drone"]["patrol_altitude_m"]) * 120))
        truth = self.truth.get(bay_id, "ok")
        img = render_bay(bay_id, truth, seed=self._frame_seq % 3, offset_px=off)
        return Frame(self.clock(), img, "sim", bay_id, {"truth": truth})

    def video_frames(self) -> Iterator[Frame]:
        while True:
            yield self.latest_frame()

    def reference_jpeg(self, bay_id: str) -> bytes:
        _, buf = cv2.imencode(".jpg", render_bay(bay_id, "ok", seed=99))
        return buf.tobytes()
