from __future__ import annotations

import numpy as np

from perception.calibrate_manual import solve
from perception.geometry import Camera, approx_intrinsics


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


def test_manual_calibration_recovers_camera_centre_and_hfov() -> None:
    size = (1280, 720)
    K = approx_intrinsics(*size, hfov_deg=60.0)
    T_twin_cam = _look_at(np.array([2.5, -2.0, 2.5]), np.array([2.5, 2.0, 0.5]))
    ground_truth = Camera(K, T_twin_cam, width=size[0], height=size[1])
    twin_points = np.array(
        [
            [1.2, 2.0, 0.0],
            [3.8, 2.0, 0.0],
            [3.8, 2.0, 1.8],
            [1.2, 2.0, 1.8],
            [1.2, 0.8, 0.0],
            [3.8, 0.8, 0.0],
            [1.5, 1.2, 0.0],
            [3.5, 1.2, 0.0],
        ],
        dtype=float,
    )
    pixels, depth = ground_truth.project(twin_points)
    assert np.all(depth > 0)

    estimated, reprojection_error, hfov = solve(pixels, twin_points, size)

    assert np.linalg.norm(estimated.center - ground_truth.center) < 0.05
    assert abs(hfov - 60.0) < 2.0
    assert reprojection_error < 1e-3
