"""Metric cloud geometry and the dashboard's little-endian XYZRGB format."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.spatial.transform import Rotation

Array = NDArray[np.float64]


def transform_points(points: Array, matrix: Array) -> Array:
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def back_project(depth: Array, rgb: NDArray[Any], intrinsics: Array,
                 stride: int = 4, max_depth: float = 30.0) -> tuple[Array, Array]:
    """Pinhole camera frame: X right, Y down, Z forward; axial depth, metres."""
    if stride < 1 or depth.ndim != 2 or rgb.shape[:2] != depth.shape:
        raise ValueError("Require matching depth/RGB sizes and stride >= 1")
    if intrinsics.shape != (3, 3) or min(intrinsics[0, 0], intrinsics[1, 1]) <= 0:
        raise ValueError("Intrinsics must be a 3x3 matrix with positive focal lengths")
    v, u = np.mgrid[0:depth.shape[0]:stride, 0:depth.shape[1]:stride]
    z = depth[::stride, ::stride]
    valid = np.isfinite(z) & (z > 0) & (z <= max_depth)
    x = (u - intrinsics[0, 2]) * z / intrinsics[0, 0]
    y = (v - intrinsics[1, 2]) * z / intrinsics[1, 1]
    return np.stack((x, y, z), axis=-1)[valid], rgb[::stride, ::stride][valid] / 255.0


def rigid_alignment(source: Array, target: Array) -> Array:
    """Least-squares rigid alignment, no reflection or invented scale."""
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 3:
        raise ValueError("Correspondences must be matching Nx3 arrays")
    a, b = source - source.mean(axis=0), target - target.mean(axis=0)
    if len(source) < 3 or min(np.linalg.matrix_rank(a), np.linalg.matrix_rank(b)) < 2:
        raise ValueError("At least three non-collinear correspondences are required")
    u, _, vt = np.linalg.svd(a.T @ b)
    rotation = vt.T @ np.diag([1, 1, np.linalg.det(vt.T @ u.T)]) @ u.T
    result = np.eye(4)
    result[:3, :3] = rotation
    result[:3, 3] = target.mean(axis=0) - rotation @ source.mean(axis=0)
    return result


def align_floor(points: Array, threshold: float = 0.05, iterations: int = 350,
                up: Array | None = None) -> tuple[Array, Array, dict[str, Any]]:
    """RANSAC floor with a gravity prior; reject walls and ceilings."""
    if len(points) < 3 or threshold <= 0:
        raise ValueError("Floor fitting needs >=3 points and a positive threshold")
    up = np.array([0.0, 0.0, 1.0]) if up is None else np.asarray(up, dtype=float)
    up = up / np.linalg.norm(up)
    rng = np.random.default_rng(42)
    sample = points[rng.choice(len(points), min(len(points), 12000), replace=False)]
    best: NDArray[np.bool_] | None = None
    best_count = 0
    for _ in range(iterations):
        a, b, c = sample[rng.choice(len(sample), 3, replace=False)]
        normal = np.cross(b - a, c - a)
        length = np.linalg.norm(normal)
        if length < 1e-9:
            continue
        normal /= length
        if normal @ up < 0:
            normal *= -1
        if normal @ up < np.cos(np.deg2rad(40)):
            continue
        signed = (sample - a) @ normal
        # A floor cannot have many points underneath it.
        if np.mean(signed < -2 * threshold) > 0.12:
            continue
        inliers = np.abs(signed) <= threshold
        count = int(inliers.sum())
        if count > best_count:
            best, best_count = inliers, count
    if best is None or best_count < max(3, int(len(sample) * 0.02)):
        raise ValueError("No supported floor found; check --up and scan units")
    floor = sample[best]
    centre = floor.mean(axis=0)
    _, _, vt = np.linalg.svd(floor - centre, full_matrices=False)
    normal = vt[-1]
    if normal @ up < 0:
        normal *= -1
    rotation, _ = Rotation.align_vectors([[0.0, 0.0, 1.0]], [normal])
    matrix = np.eye(4)
    matrix[:3, :3] = rotation.as_matrix()
    matrix[2, 3] = -(matrix[:3, :3] @ centre)[2]
    return transform_points(points, matrix), matrix, {
        "plane_input": [*normal.tolist(), -float(normal @ centre)],
        "inlier_fraction": best_count / len(sample), "threshold_m": threshold,
    }


def voxel_downsample(points: Array, colors: Array, voxel_m: float = 0.05,
                     max_points: int = 300000) -> tuple[Array, Array, float]:
    if voxel_m <= 0 or not 1 <= max_points <= 300000:
        raise ValueError("voxel_m > 0 and 1 <= max_points <= 300000 required")
    valid = np.isfinite(points).all(axis=1) & np.isfinite(colors).all(axis=1)
    points, colors = points[valid], colors[valid]
    if not len(points):
        raise ValueError("Cloud has no finite points")
    while True:
        _, indices = np.unique(np.floor(points / voxel_m).astype(np.int64),
                               axis=0, return_index=True)
        if len(indices) <= max_points:
            return points[indices], np.clip(colors[indices], 0, 1), voxel_m
        voxel_m *= 1.25


def export_cloud(points: Array, colors: Array, out: Path, source: str,
                 voxel_m: float = 0.05, max_points: int = 300000,
                 extra: dict[str, Any] | None = None) -> dict[str, Any]:
    points, colors, voxel_m = voxel_downsample(points, colors, voxel_m, max_points)
    out.mkdir(parents=True, exist_ok=True)
    np.column_stack((points, colors)).astype("<f4").tofile(out / "depth_points.bin")
    rgb = (colors * 255).round().astype(np.uint8)
    vertices = np.empty(len(points), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
                                           ("red", "u1"), ("green", "u1"), ("blue", "u1")])
    for i, name in enumerate(("x", "y", "z")):
        vertices[name] = points[:, i]
    for i, name in enumerate(("red", "green", "blue")):
        vertices[name] = rgb[:, i]
    header = ("ply\nformat binary_little_endian 1.0\n"
              f"element vertex {len(points)}\nproperty float x\nproperty float y\n"
              "property float z\nproperty uchar red\nproperty uchar green\n"
              "property uchar blue\nend_header\n")
    with (out / "depth.ply").open("wb") as stream:
        stream.write(header.encode("ascii"))
        stream.write(vertices.tobytes())
    metadata = dict(extra or {})
    metadata.update(source=source, n_points=len(points), point_count=len(points),
                    bbox={"min": points.min(axis=0).tolist(), "max": points.max(axis=0).tolist()},
                    bounds_min=points.min(axis=0).tolist(), bounds_max=points.max(axis=0).tolist(),
                    voxel_m=voxel_m, frame="twin", color_range=[0, 1],
                    format="little-endian float32 x,y,z,r,g,b")
    (out / "depth.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def read_cloud(path: Path, mesh_points: int = 200000) -> tuple[Array, Array]:
    suffix = path.suffix.lower()
    if suffix == ".bin":
        data = np.fromfile(path, dtype="<f4")
        if len(data) % 6:
            raise ValueError("Expected XYZRGB float32 interleaved data")
        data = data.reshape(-1, 6).astype(float)
        return data[:, :3], data[:, 3:]
    if suffix in {".las", ".laz"}:
        import laspy
        las = laspy.read(path)
        xyz = np.column_stack((las.x, las.y, las.z))
        colors = np.full_like(xyz, 0.65)
        if "red" in set(las.point_format.dimension_names):
            colors = np.column_stack((las.red, las.green, las.blue)).astype(float) / 65535
        return xyz, colors
    if suffix == ".e57":
        try:
            import pye57
        except ImportError as exc:
            raise RuntimeError("E57 needs optional dependency: pip install pye57") from exc
        scan = pye57.E57(str(path))
        chunks, rgb_chunks = [], []
        for index in range(scan.scan_count):
            data = scan.read_scan(index, colors=True, ignore_missing_fields=True)
            xyz = np.column_stack([data[f"cartesian{axis}"] for axis in "XYZ"])
            rgb = (np.column_stack([data[f"color{c}"] for c in ("Red", "Green", "Blue")]) / 255
                   if "colorRed" in data else np.full_like(xyz, 0.65))
            chunks.append(xyz)
            rgb_chunks.append(rgb)
        return np.concatenate(chunks), np.concatenate(rgb_chunks)
    import open3d as o3d
    if suffix in {".obj", ".glb", ".gltf"}:
        mesh = o3d.io.read_triangle_mesh(str(path), enable_post_processing=True)
        if not mesh.has_triangles():
            raise ValueError("Mesh contains no triangles")
        cloud = mesh.sample_points_uniformly(number_of_points=mesh_points)
    elif suffix in {".ply", ".pcd"}:
        cloud = o3d.io.read_point_cloud(str(path))
    else:
        raise ValueError(f"Unsupported scan type: {suffix}")
    points = np.asarray(cloud.points, dtype=float)
    colors = np.asarray(cloud.colors, dtype=float) if cloud.has_colors() else np.full_like(points, 0.65)
    if not len(points):
        raise ValueError("Scan contains no points")
    return points, colors
