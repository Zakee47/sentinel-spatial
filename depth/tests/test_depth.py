from pathlib import Path

import numpy as np
import pytest

from depth.bay_fill import estimate_fill
from depth.cloud import (
    align_floor,
    back_project,
    export_cloud,
    read_cloud,
    rigid_alignment,
    transform_points,
)
from depth.colmap import Camera, Pose, read_model, sparse_depth_scale


def test_back_projection():
    points, colors = back_project(
        np.full((2, 2), 2.0), np.full((2, 2, 3), 255), np.eye(3), 1
    )
    np.testing.assert_allclose(points, [[0, 0, 2], [2, 0, 2], [0, 2, 2], [2, 2, 2]])
    assert np.all(colors == 1)


def test_invalid_depth_filtered():
    points, _ = back_project(
        np.array([[np.nan, -1, 0, 40, 2]]), np.zeros((1, 5, 3)), np.eye(3), 1
    )
    assert len(points) == 1


def test_floor_alignment():
    rng = np.random.default_rng(2)
    xy = rng.uniform(-4, 4, (1200, 2))
    floor = np.c_[xy, 0.1 * xy[:, 0] + 2]
    points = np.r_[floor, rng.uniform([0, 0, 3], [4, 4, 5], (100, 3))]
    aligned, _, info = align_floor(points)
    assert np.max(np.abs(aligned[:1200, 2])) < 1e-8
    assert info["inlier_fraction"] > 0.8


def test_alignment():
    source = np.array([[0.0, 0, 0], [2, 0, 0], [0, 3, 0]])
    target = source + [0, 8, 0]
    np.testing.assert_allclose(
        transform_points(source, rigid_alignment(source, target)), target, atol=1e-9
    )
    with pytest.raises(ValueError):
        rigid_alignment(np.zeros((3, 3)), np.zeros((3, 3)))


def test_bay_fill():
    site = {
        "zones": [
            {
                "id": "one",
                "kind": "rack_bay",
                "polygon_xy": [[0, 0], [1, 0], [1, 1], [0, 1]],
                "z_range": [0, 1],
            }
        ]
    }
    points = np.array([[0.1, 0.1, 0.1], [0.2, 0.2, 0.2], [0.6, 0.6, 0.6], [1, 0, 0]])
    result = estimate_fill(points, site, 0.5)
    assert result["bays"][0]["fill_pct"] == 25
    assert estimate_fill(points, site, 0.5, False)["bays"][0]["fill_pct"] is None


def test_export_roundtrip(tmp_path: Path):
    rng = np.random.default_rng(3)
    points, colors = rng.random((1000, 3)), rng.random((1000, 3))
    metadata = export_cloud(points, colors, tmp_path, "test", max_points=40)
    assert metadata["n_points"] <= 40
    assert (tmp_path / "depth_points.bin").stat().st_size == metadata["n_points"] * 24
    binary, rgb = read_cloud(tmp_path / "depth_points.bin")
    ply, ply_rgb = read_cloud(tmp_path / "depth.ply")
    np.testing.assert_allclose(binary, ply)
    np.testing.assert_allclose(rgb, ply_rgb, atol=1 / 255)


def test_colmap_text_and_scale(tmp_path: Path):
    (tmp_path / "cameras.txt").write_text("1 PINHOLE 4 4 2 2 1 1\n")
    (tmp_path / "images.txt").write_text(
        "1 1 0 0 0 0 0 0 1 frame.jpg\n0 0 1 1 1 2 2 2 3\n"
    )
    (tmp_path / "points3D.txt").write_text(
        "1 0 0 4 0 0 0 0\n2 0 0 4 0 0 0 0\n3 0 0 4 0 0 0 0\n"
    )
    cameras, poses, points = read_model(tmp_path)
    ratio, count = sparse_depth_scale(
        np.full((4, 4), 2.0), poses["frame.jpg"], cameras[1], points
    )
    assert ratio == 2
    assert count == 3
    np.testing.assert_allclose(poses["frame.jpg"].camera_to_world(), np.eye(4))


def test_colmap_binary(tmp_path: Path):
    import struct

    (tmp_path / "cameras.bin").write_bytes(
        struct.pack("<QiiQQdddd", 1, 1, 1, 4, 4, 2, 2, 1, 1)
    )
    (tmp_path / "images.bin").write_bytes(
        struct.pack("<Qidddddddi", 1, 1, 1, 0, 0, 0, 1, 2, 3, 1)
        + b"frame.jpg\0"
        + struct.pack("<Q", 0)
    )
    cameras, poses, _ = read_model(tmp_path)
    assert cameras[1].width == 4
    np.testing.assert_allclose(
        poses["frame.jpg"].camera_to_world()[:3, 3], [-1, -2, -3]
    )


def test_sparse_missing_correspondences():
    pose = Pose("x", 1, np.eye(3), np.zeros(3), np.empty((0, 2)), [])
    with pytest.raises(ValueError):
        sparse_depth_scale(
            np.ones((2, 2)), pose, Camera("PINHOLE", 2, 2, np.ones(4)), {}
        )
