"""Pinhole camera model, pixel rays and ray/plane/box intersection in the twin frame.

Convention: T_twin_cam (4x4) maps OpenCV camera coordinates (x right, y down, z forward) to twin
coordinates (metres, Z up).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


def approx_intrinsics(width: int, height: int, hfov_deg: float = 65.0) -> np.ndarray:
    f = (width / 2) / np.tan(np.radians(hfov_deg) / 2)
    return np.array([[f, 0, width / 2], [0, f, height / 2], [0, 0, 1]], float)


@dataclass
class Camera:
    K: np.ndarray
    T_twin_cam: np.ndarray
    dist: np.ndarray | None = None
    width: int = 0
    height: int = 0

    @property
    def center(self) -> np.ndarray:
        return self.T_twin_cam[:3, 3]

    @property
    def T_cam_twin(self) -> np.ndarray:
        return np.linalg.inv(self.T_twin_cam)

    def pixel_ray(self, u: float, v: float) -> tuple[np.ndarray, np.ndarray]:
        """Origin and unit direction (twin frame) of the ray through pixel (u, v)."""
        if self.dist is not None and np.any(self.dist):
            pt = cv2.undistortPoints(np.array([[[u, v]]], float), self.K, self.dist)[0, 0]
            d_cam = np.array([pt[0], pt[1], 1.0])
        else:
            d_cam = np.linalg.inv(self.K) @ np.array([u, v, 1.0])
        d = self.T_twin_cam[:3, :3] @ d_cam
        return self.center.copy(), d / np.linalg.norm(d)

    def project(self, pts_twin: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Project (N,3) twin points to pixels. Returns (N,2) pixels and (N,) camera depth."""
        pts = np.atleast_2d(pts_twin).astype(float)
        T = self.T_cam_twin
        pc = pts @ T[:3, :3].T + T[:3, 3]
        rvec, _ = cv2.Rodrigues(T[:3, :3])
        px, _ = cv2.projectPoints(pts, rvec, T[:3, 3], self.K, self.dist if self.dist is not None else None)
        return px.reshape(-1, 2), pc[:, 2]

    def to_json(self) -> dict:
        return {
            "K": self.K.tolist(),
            "dist": (self.dist.ravel().tolist() if self.dist is not None else [0, 0, 0, 0, 0]),
            "T_twin_cam": self.T_twin_cam.ravel().tolist(),
            "image_size": [self.width, self.height],
        }

    @classmethod
    def from_json(cls, d: dict) -> Camera:
        w, h = d.get("image_size", [0, 0])
        return cls(np.array(d["K"], float), np.array(d["T_twin_cam"], float).reshape(4, 4), np.array(d.get("dist", [0] * 5), float), w, h)

    @classmethod
    def load(cls, path: Path | str) -> Camera:
        return cls.from_json(json.loads(Path(path).read_text()))


def ray_plane(origin: np.ndarray, direction: np.ndarray, plane: np.ndarray) -> np.ndarray | None:
    """Intersect a ray with plane ax+by+cz+d=0. None if parallel or behind the origin."""
    n, d = plane[:3], plane[3]
    denom = float(n @ direction)
    if abs(denom) < 1e-9:
        return None
    t = -(float(n @ origin) + d) / denom
    if t <= 0:
        return None
    return origin + t * direction


def ray_aabb(origin: np.ndarray, direction: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float | None:
    """Slab test. Returns the entry distance t >= 0 or None."""
    inv = 1.0 / np.where(np.abs(direction) < 1e-12, 1e-12, direction)
    t1, t2 = (lo - origin) * inv, (hi - origin) * inv
    tmin, tmax = float(np.max(np.minimum(t1, t2))), float(np.min(np.maximum(t1, t2)))
    if tmax < max(tmin, 0.0):
        return None
    return max(tmin, 0.0)


def closest_point_on_vertical_line(origin: np.ndarray, direction: np.ndarray, xy: np.ndarray) -> np.ndarray:
    """Point on the vertical line through (x, y) closest to the ray (used for head height)."""
    p0 = np.array([xy[0], xy[1], 0.0])
    u = np.array([0.0, 0.0, 1.0])
    w0 = origin - p0
    a, b, c = direction @ direction, direction @ u, 1.0
    d, e = direction @ w0, u @ w0
    denom = a * c - b * b
    s = (b * e - c * d) / denom if abs(denom) > 1e-9 else 0.0
    t = (a * e - b * d) / denom if abs(denom) > 1e-9 else e
    _ = s
    return p0 + t * u


def floor_position(
    cam: Camera,
    ankles: list[tuple[float, float, float]],
    plane: np.ndarray,
    min_conf: float = 0.3,
    fallback_px: tuple[float, float] | None = None,
    hips: list[tuple[float, float, float]] | None = None,
    hip_height_m: float = 0.9,
) -> tuple[np.ndarray | None, str]:
    """Ankle pixels -> rays -> floor intersection. Averages visible ankles. If both ankles are
    occluded (e.g. behind a trolley), intersects the hip rays with a plane `hip_height_m` above the
    floor and drops to the floor; last resort is `fallback_px` (bottom-centre of the person box).
    Returns (xyz, method)."""
    pts = []
    for u, v, c in ankles:
        if c >= min_conf:
            p = ray_plane(*cam.pixel_ray(u, v), plane)
            if p is not None:
                pts.append(p)
    if pts:
        return np.mean(pts, axis=0), "ankles" if len(pts) == 2 else "one_ankle"
    if hips:
        n = plane[:3] / np.linalg.norm(plane[:3])
        hip_plane = np.array([*plane[:3], plane[3] - hip_height_m * np.linalg.norm(plane[:3])])
        hp = [ray_plane(*cam.pixel_ray(u, v), hip_plane) for u, v, c in hips if c >= min_conf]
        hp = [p for p in hp if p is not None]
        if hp:
            return np.mean(hp, axis=0) - hip_height_m * n, "hips"
    if fallback_px is not None:
        p = ray_plane(*cam.pixel_ray(*fallback_px), plane)
        if p is not None:
            return p, "bbox_bottom"
    return None, "none"
