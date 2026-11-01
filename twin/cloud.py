"""Point-cloud IO and deterministic voxel reduction, without a GPU dependency."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from numpy.typing import NDArray

Cloud = NDArray[np.float64]


def validate(points: Cloud) -> Cloud:
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 6 or not len(points):
        raise ValueError("Expected a non-empty Nx6 array of x,y,z,r,g,b")
    if not np.isfinite(points).all():
        raise ValueError("Cloud contains non-finite coordinates or colours")
    if np.any((points[:, 3:] < 0) | (points[:, 3:] > 1)):
        raise ValueError("RGB must be normalized to [0,1]")
    return points


def downsample(points: Cloud, voxel_m: float = 0.035, max_points: int = 300_000) -> Cloud:
    points = validate(points)
    if voxel_m <= 0 or not 1 <= max_points <= 300_000:
        raise ValueError("voxel_m must be positive; max_points must be in [1,300000]")
    for _ in range(40):
        cells = np.floor(points[:, :3] / voxel_m).astype(np.int64)
        _, inverse = np.unique(cells, axis=0, return_inverse=True)
        count = np.bincount(inverse)
        reduced = np.column_stack(
            [np.bincount(inverse, weights=points[:, i]) / count for i in range(6)]
        )
        if len(reduced) <= max_points:
            return reduced
        voxel_m *= 1.3
    raise ValueError("Unable to reduce cloud; check coordinate range")


def write_ply(path: Path, points: Cloud) -> None:
    points = validate(points)
    dtype = np.dtype(
        [(v, "<f4") for v in ("x", "y", "z")] + [(v, "u1") for v in ("red", "green", "blue")]
    )
    data = np.empty(len(points), dtype=dtype)
    for i, key in enumerate(dtype.names or ()):
        data[key] = points[:, i] if i < 3 else np.rint(points[:, i] * 255)
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(points)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
    )
    with path.open("wb") as f:
        f.write(header.encode("ascii"))
        data.tofile(f)


def read_cloud(path: Path) -> Cloud:
    if path.suffix == ".npy":
        return validate(np.load(path, allow_pickle=False))
    if path.suffix == ".bin":
        return validate(np.fromfile(path, dtype="<f4").reshape(-1, 6))
    import trimesh

    cloud = trimesh.load(path, process=False)
    if isinstance(cloud, trimesh.points.PointCloud):
        xyz = np.asarray(cloud.vertices)
        rgba = np.asarray(cloud.colors)
    elif isinstance(cloud, trimesh.Trimesh):
        xyz = np.asarray(cloud.vertices)
        if not isinstance(cloud.visual, trimesh.visual.ColorVisuals):
            raise TypeError("PLY mesh must have vertex colours")
        rgba = np.asarray(cloud.visual.vertex_colors)
    else:
        raise TypeError("Expected a PLY point cloud or mesh, not a scene")
    return validate(np.column_stack((xyz, rgba[:, :3] / 255.0)))
