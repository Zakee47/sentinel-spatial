from __future__ import annotations

import cv2
import numpy as np

from perception.geometry import approx_intrinsics
from perception.pose import portal_object_points, pose_from_corners
from perception.site import load_site


def _look_at(eye: np.ndarray, target: np.ndarray) -> np.ndarray:
    forward = target - eye
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, np.array([0.0, 0.0, 1.0]))
    right /= np.linalg.norm(right)
    down = np.cross(forward, right)
    transform = np.eye(4)
    transform[:3, :3] = np.column_stack((right, down, forward))
    transform[:3, 3] = eye
    return transform


def _synthetic_p1_corners() -> tuple[np.ndarray, np.ndarray, np.ndarray, float, np.ndarray]:
    site = load_site()
    portal = site.portal("P1")
    T_twin_portal = portal["T"]
    portal_center = T_twin_portal[:3, 3]
    T_twin_cam = _look_at(np.array([0.6, 0.2, 1.4]), portal_center)
    T_cam_portal = np.linalg.inv(T_twin_cam) @ T_twin_portal
    rvec, _ = cv2.Rodrigues(T_cam_portal[:3, :3])
    object_points = portal_object_points(portal["size_m"])
    K = approx_intrinsics(1280, 720)
    corners, _ = cv2.projectPoints(object_points, rvec, T_cam_portal[:3, 3], K, None)
    return corners.reshape(4, 2), T_twin_cam, T_twin_portal, portal["size_m"], K


def _rotation_error_rad(estimated: np.ndarray, expected: np.ndarray) -> float:
    relative = estimated[:3, :3] @ expected[:3, :3].T
    rvec, _ = cv2.Rodrigues(relative)
    return float(np.linalg.norm(rvec))


def test_pose_from_corners_recovers_synthetic_p1_camera_pose() -> None:
    corners, expected, T_twin_portal, size_m, K = _synthetic_p1_corners()

    _, estimated, reprojection_error = pose_from_corners(corners, size_m, T_twin_portal, K)

    assert np.linalg.norm(estimated[:3, 3] - expected[:3, 3]) < 1e-4
    assert _rotation_error_rad(estimated, expected) < 1e-4
    assert reprojection_error < 1e-3


def test_pose_from_corners_tolerates_point_three_pixel_noise() -> None:
    # A 20 cm portal seen front-on from ~1.8 m is depth-limited: 0.3 px corner noise gives ~10 cm
    # median centre error, so the check is on the median over many draws, not a lucky seed.
    corners, expected, T_twin_portal, size_m, K = _synthetic_p1_corners()
    rng = np.random.default_rng(0)
    errs = []
    for _ in range(50):
        noisy = corners + rng.normal(0.0, 0.3, corners.shape)
        _, estimated, _ = pose_from_corners(noisy, size_m, T_twin_portal, K)
        errs.append(np.linalg.norm(estimated[:3, 3] - expected[:3, 3]))
    assert float(np.median(errs)) < 0.15
