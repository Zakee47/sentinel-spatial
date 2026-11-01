"""Camera pose from QR portals: OpenCV QRCodeDetector + solvePnP(SOLVEPNP_IPPE_SQUARE) -> T_twin_cam.

Portal local frame: QR centred at the origin in the portal's XY plane, +X right, +Y up, +Z out of
the code towards the viewer. T_twin_portal comes from config/site.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from perception.site import Site


def portal_object_points(size_m: float) -> np.ndarray:
    """Corner order matches cv2.QRCodeDetector: top-left, top-right, bottom-right, bottom-left."""
    s = size_m / 2
    return np.array([[-s, s, 0], [s, s, 0], [s, -s, 0], [-s, -s, 0]], dtype=np.float64)


def rt_to_T(rvec: np.ndarray, tvec: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3], _ = cv2.Rodrigues(rvec)
    T[:3, 3] = np.asarray(tvec).ravel()
    return T


@dataclass
class PortalPose:
    portal_id: str
    T_cam_portal: np.ndarray
    T_twin_cam: np.ndarray
    reproj_error_px: float
    corners_px: np.ndarray


def pose_from_corners(
    corners_px: np.ndarray, size_m: float, T_twin_portal: np.ndarray, K: np.ndarray, dist: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray, float]:
    """Returns (T_cam_portal, T_twin_cam, mean reprojection error in px)."""
    obj = portal_object_points(size_m)
    img = np.asarray(corners_px, np.float64).reshape(4, 2)
    ok, rvec, tvec = cv2.solvePnP(obj, img, K, dist, flags=cv2.SOLVEPNP_IPPE_SQUARE)
    if not ok:
        raise RuntimeError("solvePnP failed")
    proj, _ = cv2.projectPoints(obj, rvec, tvec, K, dist)
    err = float(np.linalg.norm(proj.reshape(4, 2) - img, axis=1).mean())
    T_cam_portal = rt_to_T(rvec, tvec)
    T_twin_cam = T_twin_portal @ np.linalg.inv(T_cam_portal)
    return T_cam_portal, T_twin_cam, err


def detect_portals(image: np.ndarray, site: Site, K: np.ndarray, dist: np.ndarray | None = None, default_portal: str | None = None) -> list[PortalPose]:
    """Detect QR portals; QR payload must be the portal id (e.g. "P1"), else `default_portal` is used."""
    det = cv2.QRCodeDetector()
    poses: list[PortalPose] = []
    ok, texts, points, _ = det.detectAndDecodeMulti(image)
    if not ok or points is None:
        return poses
    for text, pts in zip(texts, points):
        pid = (text or "").strip() or default_portal
        if not pid:
            continue
        try:
            p = site.portal(pid)
        except KeyError:
            continue
        T_cp, T_tc, err = pose_from_corners(pts, p["size_m"], p["T"], K, dist)
        poses.append(PortalPose(pid, T_cp, T_tc, err, np.asarray(pts).reshape(4, 2)))
    return poses
