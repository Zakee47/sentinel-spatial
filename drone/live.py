"""Video-only live capture for a human-piloted DJI Neo 2."""

from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Iterator
from typing import Any

import cv2
import mss
import numpy as np

from drone.driver import DroneDriver, Frame, NotSupported, Telemetry
from drone.source import safe_source

_SCREEN_REGION = re.compile(r"^\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$")
_NETWORK_PREFIXES = ("rtmp://", "rtsp://", "http://", "https://", "srt://")


def _parse_crop(
    crop: str | None,
) -> tuple[tuple[float, float, float, float], bool] | None:
    if crop is None:
        return None
    try:
        values = tuple(float(value.strip()) for value in crop.split(","))
    except ValueError as exc:
        raise ValueError("crop must be x,y,w,h") from exc
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        raise ValueError("crop must contain four finite values: x,y,w,h")
    x, y, width, height = values
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("crop coordinates must be non-negative with positive size")
    fractional = all(value <= 1 for value in values)
    if fractional:
        if x + width > 1 or y + height > 1:
            raise ValueError("fractional crop must fit within the frame")
    elif any(not value.is_integer() for value in values):
        raise ValueError("pixel crop values must be integers")
    return values, fractional


def _parse_region(region: str) -> tuple[int, int, int, int]:
    match = _SCREEN_REGION.match(region)
    if match is None:
        raise ValueError("screen region must be LEFT,TOP,WIDTH,HEIGHT")
    left, top, width, height = (int(value) for value in match.groups())
    if width <= 0 or height <= 0:
        raise ValueError("screen region width and height must be positive")
    return left, top, width, height


def _parse_source(
    source: str, region: str | None = None
) -> tuple[str, int | str | tuple[int, int, int, int] | None]:
    """Return (kind, value), keeping the parser independent of capture devices."""
    if source == "screen":
        return "screen", _parse_region(region) if region is not None else None
    if source.startswith("screen:"):
        return "screen", _parse_region(source.partition(":")[2])
    if region is not None:
        raise ValueError("region can only be used with source='screen'")
    if source.isdigit():
        return "video", int(source)
    return "video", source


def _portal_camera_matrix(portal: dict[str, Any], frame_wh: tuple[int, int]) -> np.ndarray:
    intrinsics = portal.get("intrinsics", portal.get("camera_matrix"))
    if isinstance(intrinsics, dict):
        width, height = frame_wh
        fx = float(intrinsics.get("fx", 0.8 * width))
        fy = float(intrinsics.get("fy", 0.8 * width))
        cx = float(intrinsics.get("cx", width / 2))
        cy = float(intrinsics.get("cy", height / 2))
        return np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]])
    if intrinsics is not None:
        matrix = np.asarray(intrinsics, dtype=np.float64)
        if matrix.size == 9:
            return matrix.reshape(3, 3)
        raise ValueError("portal intrinsics must contain a 3x3 camera matrix")
    width, height = frame_wh
    focal = 0.8 * width
    return np.array(
        [[focal, 0.0, width / 2], [0.0, focal, height / 2], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def _portal_object_corners(size_m: float) -> np.ndarray:
    half = size_m / 2
    # QR corners are assumed clockwise from image top-left. Portal +Y is up
    # and +Z points toward the camera, so the matching object order is:
    # top-left, top-right, bottom-right, bottom-left.
    return np.array(
        [
            [-half, half, 0.0],
            [half, half, 0.0],
            [half, -half, 0.0],
            [-half, -half, 0.0],
        ],
        dtype=np.float64,
    )


def pose_from_portal(
    corners_px: np.ndarray, portal: dict[str, Any], frame_wh: tuple[int, int]
) -> tuple[float, float, float, float]:
    """Estimate camera x/y/z and yaw in the twin frame from a portal QR code.

    ``corners_px`` follows OpenCV's QR detector convention: clockwise corners
    starting at image top-left. Portal coordinates use a centered square with
    +X right, +Y up, and +Z toward the observing camera.
    """
    width, height = frame_wh
    if width <= 0 or height <= 0:
        raise ValueError("frame dimensions must be positive")
    image_points = np.asarray(corners_px, dtype=np.float64).reshape(4, 2)
    camera_matrix = _portal_camera_matrix(portal, frame_wh)
    ok, rvec, tvec = cv2.solvePnP(
        _portal_object_corners(float(portal["size_m"])),
        image_points,
        camera_matrix,
        np.asarray(portal.get("dist_coeffs", np.zeros(5)), dtype=np.float64),
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not ok:
        raise ValueError("could not solve camera pose from portal corners")

    rotation_camera_portal, _ = cv2.Rodrigues(rvec)
    position_portal = -rotation_camera_portal.T @ tvec.reshape(3)
    camera_forward_portal = rotation_camera_portal.T @ np.array([0.0, 0.0, 1.0])

    transform_data = portal.get("T_twin_portal")
    transform = (
        np.asarray(transform_data, dtype=np.float64).reshape(4, 4)
        if transform_data is not None
        else np.eye(4, dtype=np.float64)
    )
    position_twin = transform[:3, :3] @ position_portal + transform[:3, 3]
    forward_twin = transform[:3, :3] @ camera_forward_portal
    yaw_deg = math.degrees(math.atan2(float(forward_twin[1]), float(forward_twin[0])))
    return (
        float(position_twin[0]),
        float(position_twin[1]),
        float(position_twin[2]),
        yaw_deg,
    )


class LiveFeedDriver(DroneDriver):
    """Capture video from a camera, stream URL, local file, or desktop region."""

    mode = "live"

    def __init__(
        self,
        source: str,
        site: dict[str, Any],
        fps: float = 10,
        region: str | None = None,
        crop: str | None = None,
    ) -> None:
        if fps <= 0:
            raise ValueError("fps must be positive")
        self.source = source
        self.site = site
        self.fps = fps
        self._crop = _parse_crop(crop)
        self._kind, self._capture_source = _parse_source(source, region)
        self._screen_region = (
            self._capture_source if self._kind == "screen" else None
        )
        self._network_source = (
            self._kind == "video"
            and isinstance(self._capture_source, str)
            and self._capture_source.lower().startswith(_NETWORK_PREFIXES)
        )
        self._retry_capture = self._kind == "screen" or isinstance(
            self._capture_source, int
        ) or self._network_source
        self.feed_url = (
            safe_source(source)
            if source.lower().startswith(("rtmp://", "http://", "https://"))
            else None
        )
        self._stop = threading.Event()
        self._frame_lock = threading.Lock()
        self._telemetry_lock = threading.Lock()
        self._latest: Frame | None = None
        self._frame_version = 0
        self._processed_frame_ts = 0.0
        self._last_position = (0.0, 0.0, 0.0, 0.0)
        self._last_fix_ts = 0.0
        self._portals = {
            str(portal["id"]).casefold(): portal for portal in site.get("portals", [])
        }
        self._thread = threading.Thread(
            target=self._read_loop, name="live-feed-reader", daemon=True
        )
        self._thread.start()

    def _publish_image(self, image: np.ndarray) -> None:
        if self._crop is not None:
            values, fractional = self._crop
            height, width = image.shape[:2]
            if fractional:
                left = round(values[0] * width)
                top = round(values[1] * height)
                crop_width = round(values[2] * width)
                crop_height = round(values[3] * height)
            else:
                left, top, crop_width, crop_height = (int(value) for value in values)
            left = min(left, width - 1)
            top = min(top, height - 1)
            right = min(left + max(crop_width, 1), width)
            bottom = min(top + max(crop_height, 1), height)
            image = image[top:bottom, left:right]
        frame = Frame(ts=time.monotonic(), image=image, source="live")
        with self._frame_lock:
            self._latest = frame
            self._frame_version += 1

    def _read_screen(self) -> None:
        delay = 0.25
        while not self._stop.is_set():
            try:
                with mss.mss() as grabber:
                    if self._screen_region is None:
                        monitor = grabber.monitors[1]
                    else:
                        left, top, width, height = self._screen_region
                        monitor = {
                            "left": left,
                            "top": top,
                            "width": width,
                            "height": height,
                        }
                    while not self._stop.is_set():
                        pixels = np.asarray(grabber.grab(monitor))
                        self._publish_image(cv2.cvtColor(pixels, cv2.COLOR_BGRA2BGR))
                        self._stop.wait(1 / self.fps)
                delay = 0.25
            except (mss.exception.ScreenShotError, OSError):
                if self._stop.wait(delay):
                    break
                delay = min(delay * 2, 5.0)

    def _read_video(self) -> None:
        delay = 0.25
        while not self._stop.is_set():
            capture = cv2.VideoCapture(self._capture_source)
            if capture.isOpened():
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                while not self._stop.is_set():
                    ok, image = capture.read()
                    if not ok or image is None:
                        break
                    delay = 0.25
                    self._publish_image(image)
                    if not self._network_source:
                        self._stop.wait(1 / self.fps)
                capture.release()
                if not self._retry_capture:
                    break
            else:
                capture.release()
                if not self._retry_capture:
                    break
            if self._stop.wait(delay):
                break
            delay = min(delay * 2, 5.0)

    def _read_loop(self) -> None:
        if self._kind == "screen":
            self._read_screen()
        else:
            self._read_video()

    def latest_frame(self) -> Frame | None:
        """Return the newest captured frame immediately, without waiting."""
        with self._frame_lock:
            return self._latest

    def video_frames(self) -> Iterator[Frame]:
        """Yield new frames no faster than the requested sampling rate."""
        period = 1 / self.fps
        previous_version = 0
        while not self._stop.wait(period):
            with self._frame_lock:
                frame = self._latest
                version = self._frame_version
            if frame is not None and version != previous_version:
                previous_version = version
                yield frame

    def telemetry(self) -> Telemetry:
        ts = time.monotonic()
        frame = self.latest_frame()
        with self._telemetry_lock:
            if frame is not None and frame.ts > self._processed_frame_ts:
                self._processed_frame_ts = frame.ts
                height, width = frame.image.shape[:2]
                text, corners, _ = cv2.QRCodeDetector().detectAndDecode(frame.image)
                portal_id = text.strip().casefold()
                if portal_id.startswith("sentinel:"):
                    portal_id = portal_id.partition(":")[2]
                portal = self._portals.get(portal_id)
                if portal is not None and corners is not None and ts - frame.ts < 2:
                    try:
                        self._last_position = pose_from_portal(
                            corners, portal, (width, height)
                        )
                        self._last_fix_ts = ts
                    except (KeyError, TypeError, ValueError, cv2.error):
                        pass

            has_fix = self._last_fix_ts > 0 and ts - self._last_fix_ts < 2
            x, y, z, yaw_deg = self._last_position
            return Telemetry(
                ts=ts,
                x=x,
                y=y,
                z=z,
                yaw_deg=yaw_deg,
                battery_pct=100.0,
                has_fix=has_fix,
                fix_source="portal" if has_fix else "none",
                airborne=True,
                last_fix_ts=self._last_fix_ts,
            )

    def takeoff(self) -> None:
        raise NotSupported("Neo 2 is human-piloted via DJI Fly; live mode is video-only.")

    def land(self) -> None:
        raise NotSupported("Neo 2 is human-piloted via DJI Fly; live mode is video-only.")

    def send_velocity(self, vx: float, vy: float, vz: float, yaw_rate: float) -> None:
        raise NotSupported("Neo 2 is human-piloted via DJI Fly; live mode is video-only.")

    def close(self) -> None:
        self._stop.set()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)


class NeoDriver(DroneDriver):
    """TODO: review the DJI Fly control-path findings under docs/rea/ first."""

    mode = "neo"

    def takeoff(self) -> None:
        raise NotSupported("TODO: review docs/rea/ before any Neo control implementation.")

    def land(self) -> None:
        raise NotSupported("TODO: review docs/rea/ before any Neo control implementation.")

    def send_velocity(self, vx: float, vy: float, vz: float, yaw_rate: float) -> None:
        raise NotSupported("TODO: review docs/rea/ before any Neo control implementation.")

    def video_frames(self) -> Iterator[Frame]:
        raise NotSupported("TODO: review docs/rea/ before any Neo control implementation.")

    def telemetry(self) -> Telemetry:
        raise NotSupported("TODO: review docs/rea/ before any Neo control implementation.")

    def latest_frame(self) -> Frame | None:
        raise NotSupported("TODO: review docs/rea/ before any Neo control implementation.")

    def close(self) -> None:
        raise NotSupported("TODO: review docs/rea/ before any Neo control implementation.")

    def step(self, dt: float) -> None:
        raise NotSupported("TODO: review docs/rea/ before any Neo control implementation.")


class TelloDriver(DroneDriver):
    """TODO: see docs/rea/ and the Tello SDK (UDP 8889 commands, video UDP 11111).

    Any future control implementation must be wrapped by the safety supervisor;
    DJI safety features must never be bypassed.
    """

    mode = "tello"

    def takeoff(self) -> None:
        raise NotSupported("TODO: see docs/rea/; Tello commands use UDP 8889.")

    def land(self) -> None:
        raise NotSupported("TODO: see docs/rea/; Tello commands use UDP 8889.")

    def send_velocity(self, vx: float, vy: float, vz: float, yaw_rate: float) -> None:
        raise NotSupported("TODO: see docs/rea/; Tello commands use UDP 8889.")

    def video_frames(self) -> Iterator[Frame]:
        raise NotSupported("TODO: see docs/rea/; Tello video is delivered over UDP 11111.")

    def telemetry(self) -> Telemetry:
        raise NotSupported("TODO: see docs/rea/; Tello commands use UDP 8889.")

    def latest_frame(self) -> Frame | None:
        raise NotSupported("TODO: see docs/rea/; Tello video is delivered over UDP 11111.")

    def close(self) -> None:
        raise NotSupported("TODO: see docs/rea/; Tello commands use UDP 8889.")

    def step(self, dt: float) -> None:
        raise NotSupported("TODO: see docs/rea/; Tello commands use UDP 8889.")
