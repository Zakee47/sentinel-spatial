"""Observed occupied-voxel fraction; not inferred stock volume or a stock decision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from matplotlib.path import Path as PolygonPath

from depth.cloud import Array, read_cloud


def estimate_fill(
    points: Array, site: dict[str, Any], voxel_m: float = 0.2, registered: bool = True
) -> dict[str, Any]:
    if voxel_m <= 0:
        raise ValueError("voxel_m must be positive")
    points = points[np.isfinite(points).all(axis=1)]
    result: dict[str, Any] = {
        "metric": "observed_occupied_voxel_fraction",
        "voxel_m": voxel_m,
        "registered": registered,
        "warning": "Unseen space is unknown, not empty; surfaces are not solid volume.",
        "bays": [],
    }
    for zone in site["zones"]:
        if zone["kind"] != "rack_bay":
            continue
        polygon = np.asarray(zone["polygon_xy"], dtype=float)
        lower = np.r_[polygon.min(axis=0), zone["z_range"][0]]
        upper = np.r_[polygon.max(axis=0), zone["z_range"][1]]
        shape = np.ceil((upper - lower) / voxel_m).astype(int)
        if np.any(shape <= 0):
            raise ValueError(f"Invalid bay bounds: {zone['id']}")
        # Half-open boxes ensure a shared face is not counted in both bays.
        mask = np.all((points >= lower) & (points < upper), axis=1)
        candidates = points[mask]
        if len(candidates):
            inside = PolygonPath(polygon).contains_points(
                candidates[:, :2], radius=1e-9
            )
            candidates = candidates[inside]
        occupied = len(
            np.unique(np.floor((candidates - lower) / voxel_m).astype(int), axis=0)
        )
        x = lower[0] + (np.arange(shape[0]) + 0.5) * (upper[0] - lower[0]) / shape[0]
        y = lower[1] + (np.arange(shape[1]) + 0.5) * (upper[1] - lower[1]) / shape[1]
        xx, yy = np.meshgrid(x, y)
        xy_count = (
            PolygonPath(polygon).contains_points(np.c_[xx.ravel(), yy.ravel()]).sum()
        )
        total = int(xy_count * shape[2])
        result["bays"].append(
            {
                "zone_id": zone["id"],
                "n_points": len(candidates),
                "occupied_voxels": occupied,
                "total_voxels": total,
                "fill_pct": round(min(100.0, 100 * occupied / max(total, 1)), 3)
                if registered
                else None,
                "status": "observed_surface_proxy" if registered else "unregistered",
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "file", type=Path, nargs="?", default=Path("depth/out/depth_points.bin")
    )
    parser.add_argument("--site", type=Path, default=Path("config/site.yaml"))
    parser.add_argument("--voxel-m", type=float, default=0.2)
    parser.add_argument(
        "--registered", action="store_true", help="Explicitly confirm twin registration"
    )
    args = parser.parse_args()
    points, _ = read_cloud(args.file)
    metadata_path = args.file.parent / "depth.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    registered = args.registered or metadata.get("registration") in {
        "point_correspondences",
        "twin_transform",
    }
    print(
        json.dumps(
            estimate_fill(
                points, yaml.safe_load(args.site.read_text()), args.voxel_m, registered
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
