"""Render a portable evidence image without an OpenGL/display dependency."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from depth.cloud import read_cloud


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "cloud", type=Path, nargs="?", default=Path("depth/out/depth_points.bin")
    )
    parser.add_argument("--out", type=Path, default=Path("depth/out/cloud.png"))
    parser.add_argument("--image", type=Path)
    parser.add_argument("--depth", type=Path)
    args = parser.parse_args()
    points, colors = read_cloud(args.cloud)
    indices = np.random.default_rng(42).choice(
        len(points), min(len(points), 40000), replace=False
    )
    points, colors = points[indices], colors[indices]
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(16, 9), facecolor="#111827")
    grid = fig.add_gridspec(2, 2, width_ratios=[1, 1.6], hspace=0.15, wspace=0.08)
    if args.image:
        ax = fig.add_subplot(grid[0, 0])
        ax.imshow(Image.open(args.image))
        ax.set_title(
            "REAL VIDEO · Tiger Lily / Pexels 4294436", fontsize=11, loc="left"
        )
        ax.axis("off")
    if args.depth:
        ax = fig.add_subplot(grid[1, 0])
        values = np.load(args.depth)
        im = ax.imshow(values, cmap="magma", vmin=0, vmax=np.percentile(values, 99))
        fig.colorbar(im, ax=ax, shrink=0.65, label="Predicted axial depth (m)")
        ax.set_title(
            "LEARNED DEPTH · Depth Anything V2 Metric Indoor Small",
            fontsize=10,
            loc="left",
        )
        ax.axis("off")
    ax = fig.add_subplot(grid[:, 1], projection="3d")
    ax.scatter(
        points[:, 0], points[:, 1], points[:, 2], c=colors, s=0.8, depthshade=False
    )
    ax.set(xlabel="X forward (m)", ylabel="Y left (m)", zlabel="Z up (m)")
    span = np.maximum(np.ptp(points, axis=0), 0.1)
    ax.set_box_aspect(span)
    ax.view_init(elev=19, azim=-135)
    ax.set_title(f"{len(points):,} rendered points · RGB back-projection", fontsize=13)
    metadata_path = args.cloud.parent / "depth.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    fig.suptitle(
        "SENTINEL  /  VIDEO → PSEUDO-LIDAR", x=0.05, y=0.97, ha="left", fontsize=22
    )
    fig.text(
        0.05,
        0.035,
        "Not measured LiDAR. Approximate camera calibration. "
        f"Registration: {metadata.get('registration', 'unknown')}. No motion fusion without poses.",
        fontsize=11,
        color="#cbd5e1",
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=110, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    print(args.out)


if __name__ == "__main__":
    main()
