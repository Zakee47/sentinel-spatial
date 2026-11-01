"""Head direction from COCO keypoints, gaze cone vs shelf zone boxes, look/interest state machine.

Head direction: keypoint head-yaw estimate (nose / eyes / ears relative to the head centre), used
instead of 6DRepNet360 for the hackathon build (see README). Output is a unit vector in the twin.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from perception.geometry import Camera, closest_point_on_vertical_line, ray_aabb
from perception.site import Zone

NOSE, LEYE, REYE, LEAR, REAR, LSH, RSH = 0, 1, 2, 3, 4, 5, 6


def head_yaw_from_keypoints(kp: np.ndarray, min_conf: float = 0.35) -> tuple[float, bool] | None:
    """Return (yaw_rad, facing_camera) where yaw is the head rotation about the vertical axis,
    0 = straight towards the camera (if facing_camera) or straight away from it, positive = towards
    image +u. kp: (17, 3) [u, v, conf]."""
    c = kp[:, 2]
    face = c[NOSE] >= min_conf and (c[LEYE] >= min_conf or c[REYE] >= min_conf)
    ears = [i for i in (LEAR, REAR) if c[i] >= min_conf]
    shoulders = [i for i in (LSH, RSH) if c[i] >= min_conf]
    if len(ears) == 2:
        center_u = kp[ears, 0].mean()
        half_w = abs(kp[LEAR, 0] - kp[REAR, 0]) / 2
    elif len(shoulders) == 2:
        center_u = kp[shoulders, 0].mean()
        half_w = abs(kp[LSH, 0] - kp[RSH, 0]) / 3
    else:
        return None
    half_w = max(half_w, 1e-3)
    if face:
        s = float(np.clip((kp[NOSE, 0] - center_u) / half_w, -1, 1))
        return float(np.arcsin(s)), True
    if len(ears) == 1:
        # profile: only one ear visible -> looking ~90 deg sideways, away from that ear
        side = 1.0 if kp[ears[0], 0] < center_u else -1.0
        return side * np.pi / 2 * 0.9, False
    if ears:
        return 0.0, False  # back of the head
    return None


def head_direction_twin(cam: Camera, head_xyz: np.ndarray, yaw: float, facing_camera: bool, pitch_deg: float = -12.0) -> np.ndarray:
    """Convert a camera-relative head yaw into a unit gaze direction in the twin frame."""
    to_cam = cam.center - head_xyz
    to_cam[2] = 0
    n = np.linalg.norm(to_cam)
    base = to_cam / n if n > 1e-6 else np.array([0.0, -1.0, 0.0])
    if not facing_camera:
        base = -base
    # image +u direction projected onto the floor
    right = cam.T_twin_cam[:3, 0].copy()
    right[2] = 0
    right /= max(np.linalg.norm(right), 1e-6)
    # rotate base towards `right` by |yaw| (sign chosen so +yaw turns to image +u)
    d = np.cos(yaw) * base + np.sin(yaw) * right
    d /= np.linalg.norm(d)
    p = np.radians(pitch_deg)
    g = np.array([d[0] * np.cos(p), d[1] * np.cos(p), np.sin(p)])
    return g / np.linalg.norm(g)


def head_position(cam: Camera, head_px: tuple[float, float], floor_xy: np.ndarray, default_h: float = 1.6) -> np.ndarray:
    o, d = cam.pixel_ray(*head_px)
    p = closest_point_on_vertical_line(o, d, floor_xy)
    if not (1.0 <= p[2] <= 2.1):
        p[2] = default_h
    return p


def cone_rays(direction: np.ndarray, half_angle_deg: float, n_ring: int = 8) -> list[np.ndarray]:
    d = direction / np.linalg.norm(direction)
    a = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(d, a)
    u /= np.linalg.norm(u)
    v = np.cross(d, u)
    rays = [d]
    for r_frac in (0.5, 1.0):
        ang = np.radians(half_angle_deg) * r_frac
        for k in range(n_ring):
            phi = 2 * np.pi * k / n_ring
            r = np.cos(ang) * d + np.sin(ang) * (np.cos(phi) * u + np.sin(phi) * v)
            rays.append(r / np.linalg.norm(r))
    return rays


@dataclass
class GazeHit:
    zone_id: str | None
    fraction: float
    hit_xyz: np.ndarray | None
    per_zone: dict[str, float] = field(default_factory=dict)


def cast_gaze(origin: np.ndarray, direction: np.ndarray, zones: list[Zone], half_angle_deg: float, max_dist: float = 6.0) -> GazeHit:
    rays = cone_rays(direction, half_angle_deg)
    counts: dict[str, int] = {}
    hits: dict[str, list[np.ndarray]] = {}
    for r in rays:
        best: tuple[float, Zone] | None = None
        for z in zones:
            t = ray_aabb(origin, r, z.box_min, z.box_max)
            if t is not None and t <= max_dist and (best is None or t < best[0]):
                best = (t, z)
        if best:
            counts[best[1].id] = counts.get(best[1].id, 0) + 1
            hits.setdefault(best[1].id, []).append(origin + best[0] * r)
    if not counts:
        return GazeHit(None, 0.0, None)
    zid = max(counts, key=counts.get)
    per = {k: v / len(rays) for k, v in counts.items()}
    return GazeHit(zid, per[zid], np.mean(hits[zid], axis=0), per)


@dataclass
class _LookState:
    zone_id: str
    start_t: float
    last_t: float
    hits: list[np.ndarray] = field(default_factory=list)
    interest_emitted: bool = False


class LookTracker:
    """Per-track gaze dwell on a zone. Emits `look` when a dwell ≥ look_min_s ends and `interest`
    as soon as a dwell reaches interest_min_s. Short gaze dropouts (≤ gap_s) don't break a dwell."""

    def __init__(self, look_min_s: float, interest_min_s: float, gap_s: float = 0.6):
        self.look_min_s, self.interest_min_s, self.gap_s = look_min_s, interest_min_s, gap_s
        self.state: dict[str, _LookState] = {}

    def update(self, track_id: str, t: float, zone_id: str | None, hit_xyz: np.ndarray | None = None) -> list[dict]:
        out: list[dict] = []
        st = self.state.get(track_id)
        if st and (zone_id != st.zone_id and (zone_id is not None or t - st.last_t > self.gap_s)):
            out += self._close(track_id)
            st = None
        if zone_id is None:
            return out
        if st is None:
            st = self.state[track_id] = _LookState(zone_id, t, t)
        st.last_t = t
        if hit_xyz is not None:
            st.hits.append(np.asarray(hit_xyz))
        dur = st.last_t - st.start_t
        if dur >= self.interest_min_s and not st.interest_emitted:
            st.interest_emitted = True
            out.append({"type": "interest", "track_id": track_id, "zone_id": zone_id, "payload": {"duration_s": round(dur, 2)}})
        return out

    def expire(self, t: float) -> list[dict]:
        out: list[dict] = []
        for tid in [k for k, s in self.state.items() if t - s.last_t > self.gap_s]:
            out += self._close(tid)
        return out

    def flush(self) -> list[dict]:
        out: list[dict] = []
        for tid in list(self.state):
            out += self._close(tid)
        return out

    def _close(self, track_id: str) -> list[dict]:
        st = self.state.pop(track_id, None)
        if not st:
            return []
        dur = st.last_t - st.start_t
        if dur < self.look_min_s:
            return []
        hit = np.mean(st.hits, axis=0).round(3).tolist() if st.hits else None
        return [{"type": "look", "track_id": track_id, "zone_id": st.zone_id, "payload": {"duration_s": round(dur, 2), "gaze_hit_xyz": hit}}]


class PassByTracker:
    """Emits `pass_by` the first time a track's floor point enters the aisle floor zone."""

    def __init__(self, aisle: Zone):
        self.aisle = aisle
        self.seen: set[str] = set()

    def update(self, track_id: str, xy: np.ndarray | None) -> list[dict]:
        if xy is None or track_id in self.seen or not self.aisle.contains_xy(float(xy[0]), float(xy[1])):
            return []
        self.seen.add(track_id)
        return [{"type": "pass_by", "track_id": track_id, "zone_id": self.aisle.id, "payload": {}}]
