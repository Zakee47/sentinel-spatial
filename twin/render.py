"""Render a point-cloud evidence image using the CPU-only matplotlib backend."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from twin.cloud import read_cloud


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("twin/out/twin_points.bin"))
    parser.add_argument("--out", type=Path, default=Path("twin/out/preview.png"))
    args = parser.parse_args()
    points = read_cloud(args.input)
    count = len(points)
    metadata_path = args.input.parent / "twin.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    synthetic = metadata.get("source") == "boxes"
    points = points[:: max(1, len(points) // 100_000)]
    fig = plt.figure(figsize=(16, 10), facecolor="#0e1720")
    ax = fig.add_subplot(111, projection="3d", facecolor="#0e1720")
    ax.scatter(
        *points[:, :3].T,
        c=np.clip(points[:, 3:] * 1.15, 0, 1),
        s=1.4,
        depthshade=False,
        linewidths=0,
        rasterized=True,
    )
    ax.view_init(elev=28, azim=-63)
    ax.set_box_aspect(np.maximum(np.ptp(points[:, :3], axis=0), 0.1))
    ax.set(xlabel="X / metres", ylabel="Y / metres", zlabel="Z / metres")
    ax.tick_params(colors="#a6b8c6", labelsize=8)
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.label.set_color("#a6b8c6")
        axis.set_pane_color((0.06, 0.10, 0.14, 1))
    fig.text(
        0.07,
        0.93,
        "SENTINEL  /  METRIC DIGITAL TWIN",
        color="white",
        size=23,
        weight="bold",
    )
    fig.text(
        0.07,
        0.89,
        ("PROCEDURAL FALLBACK  •  NO CAPTURED VIDEO" if synthetic else "COLMAP RECONSTRUCTION")
        + "  •  Z-UP  •  METRES",
        color="#76c7be",
        size=11,
    )
    fig.text(
        0.07,
        0.07,
        (
            "Retail: 4 sections / 20 SKUs     Racking: 4 bays / 3 levels\n"
            "B-02: empty lower centre pick face     B-03: misplaced red carton"
        )
        if synthetic
        else f"{count:,} reconstructed points / metric alignment / floor Z = 0",
        color="#b3c6d4",
        size=12,
        linespacing=1.6,
    )
    fig.savefig(args.out, dpi=125, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(args.out)


if __name__ == "__main__":
    main()
