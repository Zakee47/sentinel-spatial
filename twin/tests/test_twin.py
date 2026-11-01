from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
import trimesh
import yaml
from twin.anchor import apply_transform, correspondences, portal_corners, similarity
from twin.boxes import ROOT, generate
from twin.cloud import downsample, read_cloud, validate
from twin.export import export_cloud
from twin.extract_frames import extract, filter_blurry_frames
from twin.floor import align_floor, floor_transform
from twin.portals import (
    detect_portals,
    load_cameras,
    load_images,
    quaternion_rotation,
    triangulate,
)


def cloud(xyz: np.ndarray) -> np.ndarray:
    return np.column_stack((xyz, np.full_like(xyz, 0.5)))


def test_similarity_recovers_metric_rotation_scale_translation() -> None:
    rng = np.random.default_rng(42)
    source = rng.normal(size=(20, 3))
    rotation = quaternion_rotation(np.array([0.8, 0.2, 0.3, -0.1]))
    target = 2.8 * source @ rotation.T + np.array([1.0, 8.0, 0.5])
    transform, rmse = similarity(source, target)
    assert rmse < 1e-12
    np.testing.assert_allclose(apply_transform(cloud(source), transform)[:, :3], target, atol=1e-12)
    assert np.linalg.det(transform[:3, :3]) > 0


@pytest.mark.parametrize(
    "source",
    [
        np.zeros((2, 3)),
        np.zeros((3, 3)),
        np.array([[0.0, 0, 0], [1, 0, 0], [2, 0, 0]]),
        np.full((3, 3), np.nan),
    ],
)
def test_similarity_rejects_degenerate_picks(source: np.ndarray) -> None:
    with pytest.raises(ValueError):
        similarity(source, source)


def test_three_manual_picks_and_portal_corner_alignment() -> None:
    site = yaml.safe_load((ROOT / "config/site.yaml").read_text())
    portal = site["portals"][1]
    target = portal_corners(portal)
    source = (target - np.array([4.0, 2.0, 1.0])) / 3
    a, b = correspondences(
        {"portals": [{"id": portal["id"], "colmap_corners": source.tolist()}]}, site
    )
    transform, rmse = similarity(a, b)
    assert rmse < 1e-12
    np.testing.assert_allclose(np.linalg.norm(transform[:3, 0]), 3)
    manual = json.loads((ROOT / "twin/examples/alignment.json").read_text())
    a, b = correspondences(manual, site)
    transform, rmse = similarity(a, b)
    assert rmse < 1e-12
    np.testing.assert_allclose(transform[:3, :3], np.eye(3) * 5, atol=1e-12)


def test_floor_transform_tilt_and_offset() -> None:
    plane = np.array([0.03, -0.04, 1.0, 0.1])
    xy = np.random.default_rng(4).uniform(-3, 3, size=(100, 2))
    xyz = np.column_stack((xy, -(xy @ plane[:2] + plane[3]) / plane[2]))
    transform = floor_transform(plane)
    result = apply_transform(cloud(xyz), transform)
    np.testing.assert_allclose(result[:, 2], 0, atol=1e-12)
    np.testing.assert_allclose(transform[:3, :3] @ transform[:3, :3].T, np.eye(3), atol=1e-12)
    np.testing.assert_allclose(floor_transform(-plane), transform)


def test_ransac_prefers_near_ground_over_wall_and_high_shelf() -> None:
    rng = np.random.default_rng(0)
    xy = rng.uniform(0, 4, size=(1000, 2))
    floor = np.column_stack((xy, 0.02 * xy[:, 0] + 0.05))
    wall = np.column_stack((np.zeros(1500), rng.uniform(0, 4, size=(1500, 2))))
    shelf = np.column_stack((rng.uniform(0, 4, size=(3000, 2)), np.ones(3000) * 1.4))
    result, report = align_floor(cloud(np.concatenate((floor, wall, shelf))))
    assert report["inlier_count"] >= 1000
    assert np.max(np.abs(result[:1000, 2])) < 0.01


def test_ransac_rejects_only_wall() -> None:
    rng = np.random.default_rng(0)
    xyz = np.column_stack((np.zeros(1000), rng.uniform(0, 1, size=(1000, 2))))
    with pytest.raises(ValueError):
        align_floor(cloud(xyz))


def test_voxel_average_and_hard_point_cap() -> None:
    points = np.array([[0.01, 0.01, 0.01, 1.0, 0.0, 0.0], [0.02, 0.02, 0.02, 0.0, 0.0, 1.0]])
    np.testing.assert_allclose(downsample(points, 0.1), [[0.015, 0.015, 0.015, 0.5, 0, 0.5]])
    random = cloud(np.random.default_rng(0).uniform(0, 10, size=(1000, 3)))
    assert 1 <= len(downsample(random, 0.01, max_points=50)) <= 50


@pytest.mark.parametrize(
    "bad",
    [
        np.zeros((0, 6)),
        np.zeros((1, 5)),
        np.full((1, 6), np.nan),
        np.array([[0.0, 0.0, 0.0, 255.0, 0.0, 0.0]]),
    ],
)
def test_cloud_validation_rejects_bad_input(bad: np.ndarray) -> None:
    with pytest.raises(ValueError):
        validate(bad)


def test_export_byte_layout_and_ply_roundtrip(tmp_path: Path) -> None:
    points = np.array([[1.0, 2.0, 0.0, 1.0, 0.0, 0.0], [3.0, 4.0, 1.0, 0.0, 0.5, 1.0]])
    meta = export_cloud(points, tmp_path, "colmap")
    assert meta["point_count"] == 2
    assert (tmp_path / "twin_points.bin").stat().st_size == 2 * 6 * 4
    np.testing.assert_allclose(read_cloud(tmp_path / "twin_points.bin"), points)
    np.testing.assert_allclose(read_cloud(tmp_path / "twin.ply")[:, :3], points[:, :3])
    np.testing.assert_allclose(
        read_cloud(tmp_path / "twin.ply")[:, 3:], points[:, 3:], atol=1 / 255
    )
    assert json.loads((tmp_path / "twin.json").read_text())["floor_plane"] == [
        0.0,
        0.0,
        1.0,
        0.0,
    ]


def test_committed_assets_match_contract_and_site() -> None:
    out = ROOT / "twin/out"
    meta = json.loads((out / "twin.json").read_text())
    points = read_cloud(out / "twin_points.bin")
    assert 0 < meta["point_count"] == len(points) <= 300_000
    assert meta["source"] == "boxes"
    np.testing.assert_allclose(meta["bounds_min"], points[:, :3].min(axis=0), atol=1e-6)
    np.testing.assert_allclose(meta["bounds_max"], points[:, :3].max(axis=0), atol=1e-6)
    assert all(path.stat().st_size < 20_000_000 for path in out.iterdir())
    scene = trimesh.load_scene(out / "scene.glb")
    assert len(scene.geometry) > 100
    np.testing.assert_allclose(scene.bounds, [[-0.5, 0.0, -0.06], [10.5, 9.7, 4.0]], atol=1e-5)
    names = {obj["name"] for obj in meta["objects"]}
    assert "bay-B-02-carton-0-1" not in names
    assert "bay-B-03-carton-0-1-misplaced" in names
    for i in range(1, 5):
        assert any(n.startswith(f"aisle-A-shelf-{i}") for n in names)
        assert any(n.startswith(f"bay-B-0{i}-upright") for n in names)


def test_box_generator_is_deterministic(tmp_path: Path) -> None:
    site = yaml.safe_load((ROOT / "config/site.yaml").read_text())
    first = generate(site, tmp_path / "a", spacing=0.15)
    second = generate(site, tmp_path / "b", spacing=0.15)
    assert first == second
    assert (tmp_path / "a/twin_points.bin").read_bytes() == (
        tmp_path / "b/twin_points.bin"
    ).read_bytes()


def test_ffmpeg_extract_fps_bounded_and_rejects_reused_directory(
    tmp_path: Path,
) -> None:
    video = tmp_path / "source with spaces.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=15",
            "-t",
            "3",
            "-c:v",
            "mpeg4",
            str(video),
        ],
        check=True,
    )
    out = tmp_path / "frames"
    assert extract(video, out, fps=2, max_frames=4, max_width=160) == 4
    report = json.loads((tmp_path / "frames.json").read_text())
    assert report["duration_s"] == 3
    assert report["sample_fps"] == pytest.approx(4 / 3)
    assert report["frame_count"] == report["sampled_count"] == 4
    import cv2

    assert cv2.imread(str(next(out.glob("*.jpg")))).shape[:2] == (120, 160)
    with pytest.raises(ValueError, match="must be empty"):
        extract(video, out)


def test_laplacian_blur_filter_rejects_blurred_frame(tmp_path: Path) -> None:
    import cv2

    sharp = ((np.indices((200, 200)).sum(axis=0) // 8) % 2 * 255).astype(np.uint8)
    blurred = cv2.GaussianBlur(sharp, (41, 41), 15)
    assert cv2.imwrite(str(tmp_path / "frame_000001.jpg"), sharp)
    assert cv2.imwrite(str(tmp_path / "frame_000002.jpg"), blurred)
    scores = filter_blurry_frames(tmp_path, 50)
    assert [score["kept"] for score in scores] == [True, False]
    assert sorted(p.name for p in tmp_path.glob("*.jpg")) == ["frame_000001.jpg"]


def test_4k_mp4_downscales_to_1600_and_retains_aspect(tmp_path: Path) -> None:
    import cv2

    video = tmp_path / "DJI_0001.MP4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=3840x2160:rate=2",
            "-t",
            "2",
            "-c:v",
            "mpeg4",
            str(video),
        ],
        check=True,
        timeout=30,
    )
    out = tmp_path / "frames"
    assert extract(video, out) == 4
    assert cv2.imread(str(next(out.glob("*.jpg")))).shape[:2] == (900, 1600)


def test_all_blurry_frames_leave_diagnostics_and_refuse_colmap(tmp_path: Path) -> None:
    video = tmp_path / "blank.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:size=160x120:rate=2",
            "-t",
            "2",
            "-c:v",
            "mpeg4",
            str(video),
        ],
        check=True,
    )
    with pytest.raises(RuntimeError, match="Only 0 sharp frames"):
        extract(video, tmp_path / "frames")
    report = json.loads((tmp_path / "frames.json").read_text())
    assert report["rejected_count"] == 4
    assert report["frame_count"] == 0


def test_colmap_pose_parser_empty_points_and_camera_models(tmp_path: Path) -> None:
    (tmp_path / "images.txt").write_text(
        "# header\n1 1 0 0 0 -1 0 0 1 a.jpg\n\n2 1 0 0 0 1 0 0 2 b.jpg\n1 2 3\n"
    )
    images = load_images(tmp_path / "images.txt")
    assert [i[0] for i in images] == ["a.jpg", "b.jpg"]
    np.testing.assert_allclose(images[0][2][:, 3], [-1, 0, 0])
    (tmp_path / "cameras.txt").write_text(
        "1 SIMPLE_RADIAL 800 800 800 400 400 0.01\n2 PINHOLE 800 800 800 810 400 400\n"
    )
    cameras = load_cameras(tmp_path / "cameras.txt")
    assert cameras[1][1][0] == 0.01
    assert cameras[2][0][1, 1] == 810


def test_triangulation_depth_parallax_and_accuracy() -> None:
    xyz = np.array([0.2, 0.1, 5.0])
    observations = []
    for tx in (-0.5, 0.5, 0.8):
        projection = np.column_stack((np.eye(3), [tx, 0.0, 0.0]))
        p = projection @ np.append(xyz, 1.0)
        observations.append((projection, p[:2] / p[2]))
    np.testing.assert_allclose(triangulate(observations), xyz, atol=1e-12)
    with pytest.raises(ValueError, match="parallax"):
        triangulate([observations[0], observations[0]])


def test_qr_detection_to_metric_portal_alignment(tmp_path: Path) -> None:
    import cv2

    images, model = tmp_path / "frames", tmp_path / "model"
    images.mkdir()
    model.mkdir()
    qr = cv2.QRCodeEncoder_create().encode("P1")
    qr = cv2.resize(qr, (400, 400), interpolation=cv2.INTER_NEAREST)
    # Encoder includes a 2-module quiet zone. The physical portal edge is the
    # black code boundary; remove quiet padding before projecting that edge.
    nonwhite = np.argwhere(qr < 128)
    y0, x0 = nonwhite.min(axis=0)
    y1, x1 = nonwhite.max(axis=0) + 1
    qr = qr[y0:y1, x0:x1]
    h, w = qr.shape
    transform = np.diag([1.0, -1.0, -1.0, 1.0])
    transform[2, 3] = 5.0
    portal = {"id": "P1", "size_m": 2.0, "T_twin_portal": transform.ravel().tolist()}
    corners = portal_corners(portal)
    poses = []
    for index, tx in enumerate((-0.6, 0.6), 1):
        xyz = corners + np.array([tx, 0, 0])
        pixels = xyz[:, :2] / xyz[:, 2:] * 800 + 400
        warp = cv2.getPerspectiveTransform(
            np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]]),
            pixels.astype(np.float32),
        )
        image = cv2.warpPerspective(qr, warp, (800, 800), borderValue=255, flags=cv2.INTER_NEAREST)
        assert cv2.imwrite(str(images / f"{index}.png"), image)
        poses.append(f"{index} 1 0 0 0 {tx} 0 0 1 {index}.png\n\n")
    (model / "cameras.txt").write_text("1 PINHOLE 800 800 800 800 400 400\n")
    (model / "images.txt").write_text("".join(poses))
    detected = detect_portals(model, images, {"portals": [portal]})
    source, target = correspondences(detected, {"portals": [portal]})
    fitted, rmse = similarity(source, target)
    assert rmse < 0.025
    np.testing.assert_allclose(fitted, np.eye(4), atol=0.04)
