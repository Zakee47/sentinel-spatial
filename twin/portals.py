"""Recover known QR corners in COLMAP space by multi-view triangulation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from twin.cloud import Cloud


def quaternion_rotation(q: Cloud) -> Cloud:
    w, x, y, z = np.asarray(q, dtype=float) / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * w * z, 2 * x * z + 2 * w * y],
            [2 * x * y + 2 * w * z, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * w * x],
            [2 * x * z - 2 * w * y, 2 * y * z + 2 * w * x, 1 - 2 * x * x - 2 * y * y],
        ]
    )


def load_cameras(path: Path) -> dict[int, tuple[Cloud, Cloud]]:
    cameras = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split()
        camera_id, model = int(fields[0]), fields[1]
        values = list(map(float, fields[4:]))
        distortion = np.zeros(5)
        if model in {"SIMPLE_PINHOLE", "SIMPLE_RADIAL", "RADIAL"}:
            f, cx, cy = values[:3]
            fx, fy = f, f
            if model != "SIMPLE_PINHOLE":
                distortion[0] = values[3]
            if model == "RADIAL":
                distortion[1] = values[4]
        elif model in {"PINHOLE", "OPENCV"}:
            fx, fy, cx, cy = values[:4]
            if model == "OPENCV":
                distortion[:4] = values[4:8]
        else:
            raise ValueError(f"Unsupported COLMAP camera model: {model}")
        cameras[camera_id] = (
            np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]]),
            distortion,
        )
    return cameras


def load_images(path: Path) -> list[tuple[str, int, Cloud]]:
    # Each image has a pose line and a second (possibly empty) POINTS2D line.
    lines = [line for line in path.read_text().splitlines() if not line.startswith("#")]
    images = []
    index = 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        fields = lines[index].split(maxsplit=9)
        if len(fields) != 10:
            raise ValueError("Malformed COLMAP images.txt pose line")
        rotation = quaternion_rotation(np.array(list(map(float, fields[1:5]))))
        translation = np.array(list(map(float, fields[5:8])))
        images.append((fields[9], int(fields[8]), np.column_stack((rotation, translation))))
        index += 2
    return images


def triangulate(observations: list[tuple[Cloud, Cloud]], max_reprojection: float = 0.008) -> Cloud:
    """DLT from normalized camera rays; require positive depth and >1 degree parallax."""
    if len(observations) < 2:
        raise ValueError("A portal must be visible in at least two registered frames")
    rows, rays = [], []
    for projection, uv in observations:
        rows.extend(
            [
                uv[0] * projection[2] - projection[0],
                uv[1] * projection[2] - projection[1],
            ]
        )
        ray = projection[:, :3].T @ np.array([*uv, 1.0])
        rays.append(ray / np.linalg.norm(ray))
    cosine = np.clip(np.array(rays) @ np.array(rays).T, -1, 1)
    if float(np.max(np.arccos(cosine))) < np.deg2rad(1):
        raise ValueError("Insufficient portal parallax; translate the camera during capture")
    _, _, vt = np.linalg.svd(np.asarray(rows))
    homogeneous = vt[-1]
    if abs(homogeneous[3]) < 1e-10:
        raise ValueError("Portal corner triangulates at infinity")
    xyz = homogeneous[:3] / homogeneous[3]
    for projection, uv in observations:
        projected = projection @ np.append(xyz, 1.0)
        if (
            projected[2] <= 0
            or np.linalg.norm(projected[:2] / projected[2] - uv) > max_reprojection
        ):
            raise ValueError("Portal corner has invalid depth or excessive reprojection error")
    return xyz


def detect_portals(model: Path, images: Path, site: dict[str, Any]) -> dict[str, Any]:
    import cv2

    cameras = load_cameras(model / "cameras.txt")
    poses = load_images(model / "images.txt")
    known = {p["id"] for p in site["portals"]}
    observations: dict[str, list[list[tuple[Cloud, Cloud]]]] = {}
    detector = cv2.QRCodeDetector()
    for name, camera_id, projection in poses:
        image = cv2.imread(str(images / name))
        if image is None:
            continue
        ok, texts, corners, _ = detector.detectAndDecodeMulti(image)
        if not ok:
            continue
        intrinsics, distortion = cameras[camera_id]
        for text, pixels in zip(texts, corners, strict=True):
            portal_id = text.removeprefix("sentinel:")
            if portal_id not in known:
                continue
            normalized = np.asarray(
                cv2.undistortPoints(
                    np.asarray(pixels, dtype=float).reshape(-1, 1, 2),
                    intrinsics,
                    distortion,
                ),
                dtype=np.float64,
            ).reshape(4, 2)
            observations.setdefault(portal_id, [[], [], [], []])
            for i, uv in enumerate(normalized):
                observations[portal_id][i].append((projection, uv))
    result = []
    for portal_id, corner_observations in observations.items():
        try:
            xyz = [triangulate(corner).tolist() for corner in corner_observations]
        except ValueError:
            continue
        result.append({"id": portal_id, "colmap_corners": xyz})
    if not result:
        raise ValueError(
            "No known QR portal triangulated. Supply --alignment with >=3 manual picks; "
            "stock footage has no Sentinel portals and cannot determine metric scale alone."
        )
    return {"portals": result}
