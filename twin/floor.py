"""Open3D RANSAC floor refinement after metric anchoring; never edits site.yaml."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from twin.anchor import apply_transform
from twin.cloud import Cloud, read_cloud


def floor_transform(plane: Cloud) -> Cloud:
    plane = np.asarray(plane, dtype=float)
    if plane.shape != (4,) or not np.isfinite(plane).all() or np.linalg.norm(plane[:3]) < 1e-12:
        raise ValueError("Expected a finite, nonzero plane [a,b,c,d]")
    plane = plane / np.linalg.norm(plane[:3])
    if plane[2] < 0:
        plane = -plane
    normal = plane[:3]
    v = np.cross(normal, [0.0, 0.0, 1.0])
    c = normal[2]
    skew = np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])
    rotation = np.eye(3) + skew + skew @ skew / (1 + c)
    transform = np.eye(4)
    transform[:3, :3] = rotation
    transform[2, 3] = plane[3]
    return transform


def align_floor(
    points: Cloud, distance_m: float = 0.03, search_height_m: float = 0.3
) -> tuple[Cloud, dict[str, object]]:
    import open3d as o3d

    if distance_m <= 0 or search_height_m <= 0:
        raise ValueError("Floor thresholds must be positive")
    # Anchoring already defines up and origin. Only refine near the expected floor,
    # otherwise the largest shelf/wall plane can be mistaken for the ground.
    candidates = points[np.abs(points[:, 2]) <= search_height_m, :3]
    if len(candidates) < 30:
        raise ValueError("Fewer than 30 points near the anchored floor; supply better picks")
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(candidates))
    o3d.utility.random.seed(0)
    for _ in range(5):
        if len(cloud.points) < 30:
            break
        plane, inliers = cloud.segment_plane(
            distance_threshold=distance_m,
            ransac_n=3,
            num_iterations=1000,
            probability=0.999,
        )
        plane = np.asarray(plane)
        if plane[2] < 0:
            plane = -plane
        if plane[2] > 0.94 and len(inliers) >= max(30, int(0.1 * len(candidates))):
            transform = floor_transform(plane)
            return apply_transform(points, transform), {
                "input_floor_plane": plane.tolist(),
                "floor_plane": [0.0, 0.0, 1.0, 0.0],
                "inlier_count": len(inliers),
                "candidate_count": len(candidates),
                "T_floor_refinement": transform.tolist(),
                "distance_threshold_m": distance_m,
            }
        cloud = cloud.select_by_index(inliers, invert=True)
    raise ValueError("No plausible near-horizontal floor found; refusing a wall/shelf alignment")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path, default=Path("twin/work/floored.npy"))
    parser.add_argument("--distance-m", type=float, default=0.03)
    parser.add_argument("--search-height-m", type=float, default=0.3)
    args = parser.parse_args()
    points, report = align_floor(read_cloud(args.input), args.distance_m, args.search_height_m)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.save(args.out, points)
    args.out.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
