"""Import real measured scans or sampled meshes into the twin frame."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from depth.cloud import align_floor, export_cloud, read_cloud, rigid_alignment, transform_points


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--out", type=Path, default=Path("depth/out"))
    parser.add_argument("--alignment", type=Path, help="JSON: scan_points and twin_points, >=3 Nx3")
    parser.add_argument("--unit-m", type=float, default=1.0, help="Metres per source unit")
    parser.add_argument("--up", choices=["x", "y", "z"], default="z")
    parser.add_argument("--voxel-m", type=float, default=0.05)
    parser.add_argument("--floor-threshold-m", type=float, default=0.05)
    args = parser.parse_args()
    if args.unit_m <= 0:
        parser.error("--unit-m must be positive")
    points, colors = read_cloud(args.file)
    points *= args.unit_m
    up = np.eye(3)["xyz".index(args.up)]
    points, matrix, floor = align_floor(points, args.floor_threshold_m, up=up)
    registration = "floor_only_unregistered_xy"
    if args.alignment:
        pairs = json.loads(args.alignment.read_text())
        source = transform_points(np.asarray(pairs["scan_points"], dtype=float) * args.unit_m, matrix)
        target = np.asarray(pairs["twin_points"], dtype=float)
        alignment = rigid_alignment(source, target)
        points = transform_points(points, alignment)
        matrix = alignment @ matrix
        floor["alignment_rmse_m"] = float(np.sqrt(np.mean(np.sum(
            (transform_points(source, alignment) - target) ** 2, axis=1))))
        registration = "point_correspondences"
    result = export_cloud(points, colors, args.out, source="scan", voxel_m=args.voxel_m,
                          extra={"input": str(args.file), "registration": registration,
                                 "floor": floor, "T_twin_metric_scan": matrix.tolist(),
                                 "input_unit_m": args.unit_m, "measured_lidar":
                                 args.file.suffix.lower() in {".las", ".laz", ".e57"}})
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
