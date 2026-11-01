"""Small read-only COLMAP text/binary reader (no pycolmap dependency)."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np
from scipy.spatial.transform import Rotation

from depth.cloud import Array

# COLMAP's registered camera-model IDs and parameter counts.
MODELS = {
    0: ("SIMPLE_PINHOLE", 3),
    1: ("PINHOLE", 4),
    2: ("SIMPLE_RADIAL", 4),
    3: ("RADIAL", 5),
    4: ("OPENCV", 8),
    5: ("OPENCV_FISHEYE", 8),
    6: ("FULL_OPENCV", 12),
    7: ("FOV", 5),
    8: ("SIMPLE_RADIAL_FISHEYE", 4),
    9: ("RADIAL_FISHEYE", 5),
    10: ("THIN_PRISM_FISHEYE", 12),
}


@dataclass
class Camera:
    model: str
    width: int
    height: int
    params: Array

    def intrinsics(self, width: int, height: int) -> Array:
        if self.model in {
            "SIMPLE_PINHOLE",
            "SIMPLE_RADIAL",
            "RADIAL",
            "SIMPLE_RADIAL_FISHEYE",
            "RADIAL_FISHEYE",
        }:
            fx, cx, cy = self.params[:3]
            fy = fx
        else:
            fx, fy, cx, cy = self.params[:4]
        sx, sy = width / self.width, height / self.height
        return np.array([[fx * sx, 0, cx * sx], [0, fy * sy, cy * sy], [0, 0, 1]])


@dataclass
class Pose:
    name: str
    camera_id: int
    rotation: Array  # world -> camera
    translation: Array
    xy: Array
    point_ids: list[int]

    def camera_to_world(self) -> Array:
        matrix = np.eye(4)
        matrix[:3, :3] = self.rotation.T
        matrix[:3, 3] = -self.rotation.T @ self.translation
        return matrix


def _rotation(qvec: list[float]) -> Array:
    return Rotation.from_quat([*qvec[1:], qvec[0]]).as_matrix()


def _unpack(stream: BinaryIO, fmt: str) -> tuple[Any, ...]:
    count = struct.calcsize("<" + fmt)
    raw = stream.read(count)
    if len(raw) != count:
        raise ValueError("Truncated COLMAP binary model")
    return struct.unpack("<" + fmt, raw)


def _read_binary(
    folder: Path,
) -> tuple[dict[int, Camera], dict[str, Pose], dict[int, Array]]:
    cameras, poses, points = {}, {}, {}
    with (folder / "cameras.bin").open("rb") as stream:
        for _ in range(_unpack(stream, "Q")[0]):
            cid, model_id, width, height = _unpack(stream, "iiQQ")
            if model_id not in MODELS:
                raise ValueError(f"Unsupported COLMAP camera model ID {model_id}")
            model, n = MODELS[model_id]
            cameras[cid] = Camera(
                model, width, height, np.array(_unpack(stream, "d" * n))
            )
    with (folder / "images.bin").open("rb") as stream:
        for _ in range(_unpack(stream, "Q")[0]):
            record = _unpack(stream, "idddddddi")
            name = bytearray()
            while True:
                char = stream.read(1)
                if not char:
                    raise ValueError("Truncated COLMAP image name")
                if char == b"\0":
                    break
                name.extend(char)
            n = _unpack(stream, "Q")[0]
            data = [_unpack(stream, "ddq") for _ in range(n)]
            image_name = name.decode("utf-8")
            poses[image_name] = Pose(
                image_name,
                record[8],
                _rotation(list(record[1:5])),
                np.array(record[5:8]),
                np.array([[p[0], p[1]] for p in data]).reshape(-1, 2),
                [p[2] for p in data],
            )
    if (folder / "points3D.bin").exists():
        with (folder / "points3D.bin").open("rb") as stream:
            for _ in range(_unpack(stream, "Q")[0]):
                record = _unpack(stream, "QdddBBBd")
                points[record[0]] = np.array(record[1:4])
                n = _unpack(stream, "Q")[0]
                stream.seek(8 * n, 1)
    return cameras, poses, points


def _lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if not line.lstrip().startswith("#")
    ]


def _read_text(
    folder: Path,
) -> tuple[dict[int, Camera], dict[str, Pose], dict[int, Array]]:
    cameras, poses, points = {}, {}, {}
    for line in _lines(folder / "cameras.txt"):
        if not line:
            continue
        parts = line.split()
        cameras[int(parts[0])] = Camera(
            parts[1], int(parts[2]), int(parts[3]), np.array(parts[4:], dtype=float)
        )
    lines = _lines(folder / "images.txt")
    index = 0
    while index < len(lines):
        if not lines[index]:
            index += 1
            continue
        parts = lines[index].split(maxsplit=9)
        index += 1
        observations = lines[index].split() if index < len(lines) else []
        index += 1
        xy = np.array(
            [
                [float(observations[i]), float(observations[i + 1])]
                for i in range(0, len(observations), 3)
            ]
        ).reshape(-1, 2)
        name = parts[9]
        poses[name] = Pose(
            name,
            int(parts[8]),
            _rotation([float(p) for p in parts[1:5]]),
            np.array(parts[5:8], dtype=float),
            xy,
            [int(observations[i]) for i in range(2, len(observations), 3)],
        )
    if (folder / "points3D.txt").exists():
        for line in _lines(folder / "points3D.txt"):
            if line:
                parts = line.split()
                points[int(parts[0])] = np.array(parts[1:4], dtype=float)
    return cameras, poses, points


def read_model(
    folder: Path,
) -> tuple[dict[int, Camera], dict[str, Pose], dict[int, Array]]:
    if (folder / "cameras.bin").exists():
        return _read_binary(folder)
    return _read_text(folder)


def find_model(root: Path = Path("twin/work")) -> Path | None:
    candidates = sorted({*root.glob("**/sparse/0"), *root.glob("**/sparse")})
    return next(
        (
            path
            for path in candidates
            if (path / "images.bin").exists() or (path / "images.txt").exists()
        ),
        None,
    )


def sparse_depth_scale(
    depth: Array, pose: Pose, camera: Camera, sparse_points: dict[int, Array]
) -> tuple[float, int]:
    """Median sparse camera-Z / predicted axial depth, rejecting gross outliers."""
    ratios = []
    for xy, point_id in zip(pose.xy, pose.point_ids, strict=True):
        if point_id not in sparse_points:
            continue
        x = round(xy[0] * depth.shape[1] / camera.width)
        y = round(xy[1] * depth.shape[0] / camera.height)
        if not (0 <= x < depth.shape[1] and 0 <= y < depth.shape[0]):
            continue
        z = (pose.rotation @ sparse_points[point_id] + pose.translation)[2]
        predicted = depth[y, x]
        if z > 0 and predicted > 0 and np.isfinite(predicted):
            ratios.append(z / predicted)
    if len(ratios) < 3:
        raise ValueError(
            f"{pose.name}: need >=3 valid sparse depth correspondences, got {len(ratios)}"
        )
    values = np.asarray(ratios)
    median = float(np.median(values))
    values = values[(values > median / 3) & (values < median * 3)]
    return float(np.median(values)), len(values)
