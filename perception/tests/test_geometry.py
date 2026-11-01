from __future__ import annotations

import numpy as np
import pytest

from perception.geometry import (
    Camera,
    approx_intrinsics,
    floor_position,
    ray_aabb,
    ray_plane,
)


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


def _floor_camera() -> Camera:
    transform = _look_at(np.array([2.0, -1.0, 2.5]), np.array([2.0, 1.0, 1.34]))
    return Camera(approx_intrinsics(1280, 720), transform, width=1280, height=720)


def _pixel_for(camera: Camera, point: np.ndarray) -> tuple[float, float]:
    pixels, depth = camera.project(np.asarray([point], dtype=float))
    assert depth[0] > 0
    return float(pixels[0, 0]), float(pixels[0, 1])


def test_ray_plane_intersects_forward_ray() -> None:
    point = ray_plane(np.array([0.0, 0.0, 2.0]), np.array([1.0, 0.0, -1.0]) / np.sqrt(2), np.array([0.0, 0.0, 1.0, 0.0]))
    assert point is not None
    np.testing.assert_allclose(point, [2.0, 0.0, 0.0], atol=1e-12)


@pytest.mark.parametrize(
    ("origin", "direction"),
    [
        ([0.0, 0.0, 2.0], [1.0, 0.0, 0.0]),
        ([0.0, 0.0, 2.0], [0.0, 0.0, 1.0]),
    ],
)
def test_ray_plane_rejects_parallel_or_behind(origin: list[float], direction: list[float]) -> None:
    assert ray_plane(np.array(origin), np.array(direction), np.array([0.0, 0.0, 1.0, 0.0])) is None


def test_camera_pixel_ray_round_trip_to_floor() -> None:
    camera = _floor_camera()
    expected = np.array([2.5, 1.2, 0.0])
    pixel = _pixel_for(camera, expected)
    origin, direction = camera.pixel_ray(*pixel)
    recovered = ray_plane(origin, direction, np.array([0.0, 0.0, 1.0, 0.0]))
    assert recovered is not None
    np.testing.assert_allclose(recovered, expected, atol=1e-6)


def test_floor_position_uses_mean_of_two_visible_ankles() -> None:
    camera = _floor_camera()
    left = np.array([1.8, 1.0, 0.0])
    right = np.array([2.2, 1.4, 0.0])
    left_px, right_px = _pixel_for(camera, left), _pixel_for(camera, right)

    point, method = floor_position(
        camera,
        [(*left_px, 0.9), (*right_px, 0.8)],
        np.array([0.0, 0.0, 1.0, 0.0]),
    )

    assert method == "ankles"
    np.testing.assert_allclose(point, (left + right) / 2, atol=1e-6)


def test_floor_position_uses_one_ankle_above_confidence_threshold() -> None:
    camera = _floor_camera()
    left = np.array([1.8, 1.0, 0.0])
    right = np.array([2.2, 1.4, 0.0])

    point, method = floor_position(
        camera,
        [(*_pixel_for(camera, left), 0.1), (*_pixel_for(camera, right), 0.9)],
        np.array([0.0, 0.0, 1.0, 0.0]),
    )

    assert method == "one_ankle"
    np.testing.assert_allclose(point, right, atol=1e-6)


def test_floor_position_uses_bbox_fallback_when_ankles_are_occluded() -> None:
    camera = _floor_camera()
    expected = np.array([2.0, 1.2, 0.0])
    fallback_px = _pixel_for(camera, expected)
    ankle_px = _pixel_for(camera, np.array([2.2, 1.3, 0.0]))

    point, method = floor_position(
        camera,
        [(*ankle_px, 0.1), (*ankle_px, 0.2)],
        np.array([0.0, 0.0, 1.0, 0.0]),
        fallback_px=fallback_px,
    )

    assert method == "bbox_bottom"
    np.testing.assert_allclose(point, expected, atol=1e-6)


def test_floor_position_returns_none_without_valid_pixels() -> None:
    point, method = floor_position(
        _floor_camera(),
        [],
        np.array([0.0, 0.0, 1.0, 0.0]),
    )
    assert point is None
    assert method == "none"


def test_ray_aabb_reports_hit_and_miss() -> None:
    lo = np.array([2.0, -1.0, -1.0])
    hi = np.array([3.0, 1.0, 1.0])
    assert ray_aabb(np.zeros(3), np.array([1.0, 0.0, 0.0]), lo, hi) == pytest.approx(2.0)
    assert ray_aabb(np.array([0.0, 2.0, 0.0]), np.array([1.0, 0.0, 0.0]), lo, hi) is None
