"""Write the fixed dashboard asset contract (little-endian float32, RGB 0..1)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from twin.cloud import Cloud, downsample, read_cloud, write_ply


def export_cloud(
    points: Cloud,
    out: Path,
    source: str,
    voxel_m: float = 0.035,
    max_points: int = 300_000,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if source not in {"boxes", "colmap", "simready"}:
        raise ValueError("Invalid twin source")
    points = downsample(points, voxel_m, max_points)
    out.mkdir(parents=True, exist_ok=True)
    points.astype("<f4").tofile(out / "twin_points.bin")
    write_ply(out / "twin.ply", points)
    metadata = dict(extra or {})
    metadata.update(
        source=source,
        point_count=len(points),
        bounds_min=points[:, :3].min(axis=0).tolist(),
        bounds_max=points[:, :3].max(axis=0).tolist(),
        floor_plane=[0.0, 0.0, 1.0, 0.0],
    )
    (out / "twin.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path, default=Path("twin/out"))
    parser.add_argument(
        "--source", choices=["boxes", "colmap", "simready"], default="colmap"
    )
    parser.add_argument("--voxel-m", type=float, default=0.035)
    parser.add_argument("--max-points", type=int, default=300_000)
    args = parser.parse_args()
    print(
        json.dumps(
            export_cloud(
                read_cloud(args.input),
                args.out,
                args.source,
                args.voxel_m,
                args.max_points,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
