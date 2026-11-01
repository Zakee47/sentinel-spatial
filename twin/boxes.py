"""Generate an explicitly synthetic, metric scene from the fixed site geometry."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
import yaml

from twin.export import export_cloud

ROOT = Path(__file__).resolve().parents[1]


def generate(site: dict[str, Any], out: Path, spacing: float = 0.045) -> dict[str, Any]:
    scene = trimesh.Scene()
    samples = []
    objects: list[dict[str, Any]] = []

    def box(name: str, lo: list[float], hi: list[float], rgb: list[int]) -> None:
        lower, upper = np.asarray(lo), np.asarray(hi)
        mesh = trimesh.creation.box(extents=upper - lower)
        mesh.apply_translation((upper + lower) / 2)
        mesh.visual.vertex_colors = np.tile([*rgb, 255], (len(mesh.vertices), 1))
        scene.add_geometry(mesh, node_name=name, geom_name=name)
        objects.append({"name": name, "bounds_min": lo, "bounds_max": hi})
        for axis in range(3):
            a, b = [i for i in range(3) if i != axis]
            u = np.linspace(
                lower[a], upper[a], max(2, int((upper[a] - lower[a]) / spacing) + 1)
            )
            v = np.linspace(
                lower[b], upper[b], max(2, int((upper[b] - lower[b]) / spacing) + 1)
            )
            uu, vv = np.meshgrid(u, v)
            for side in (lower[axis], upper[axis]):
                xyz = np.empty((uu.size, 3))
                xyz[:, axis], xyz[:, a], xyz[:, b] = side, uu.ravel(), vv.ravel()
                # Slight deterministic shading keeps the point cloud readable.
                colour = np.tile(
                    np.asarray(rgb) / 255 * (0.83 + axis * 0.07), (len(xyz), 1)
                )
                samples.append(np.column_stack((xyz, colour)))

    polygons = np.concatenate([z["polygon_xy"] for z in site["zones"]])
    xmin, ymin = polygons.min(axis=0) - 0.5
    xmax, ymax = polygons.max(axis=0) + 0.5
    box("floor", [xmin, ymin, -0.06], [xmax, ymax, 0.0], [56, 68, 78])
    product_colours = [
        [52, 167, 154],
        [218, 178, 77],
        [79, 133, 190],
        [183, 89, 111],
        [138, 158, 83],
    ]
    for zone in site["zones"]:
        poly = np.asarray(zone["polygon_xy"])
        (x0, y0), (x1, y1) = poly.min(axis=0), poly.max(axis=0)
        z0, z1 = zone["z_range"]
        name = zone["id"]
        if zone["kind"] == "retail_shelf":
            box(name + "-back", [x0, y1 - 0.035, z0], [x1, y1, z1], [120, 133, 142])
            for x in (x0, x1 - 0.035):
                box(
                    name + f"-upright-{x}",
                    [x, y0, z0],
                    [x + 0.035, y1, z1],
                    [165, 180, 192],
                )
            for level in range(4):
                h = 0.05 + level * 0.44
                box(
                    name + f"-shelf-{level}",
                    [x0, y0, h],
                    [x1, y1, h + 0.035],
                    [153, 168, 179],
                )
                for p, sku in enumerate(zone["products"]):
                    x = x0 + 0.035 + p * (x1 - x0 - 0.04) / 5
                    box(
                        f"{name}-{sku}-{level}",
                        [x, y0 + 0.035, h + 0.035],
                        [x + 0.105, y1 - 0.055, h + 0.33],
                        product_colours[p % 5],
                    )
        elif zone["kind"] == "rack_bay":
            for x in (x0, x1 - 0.07):
                for y in (y0, y1 - 0.07):
                    box(
                        name + f"-upright-{x}-{y}",
                        [x, y, z0],
                        [x + 0.07, y + 0.07, z1],
                        [59, 112, 156],
                    )
            for level, h in enumerate((0.12, 1.4, 2.7)):
                for y in (y0, y1 - 0.08):
                    box(
                        name + f"-beam-{level}-{y}",
                        [x0, y, h],
                        [x1, y + 0.08, h + 0.12],
                        [224, 132, 49],
                    )
                box(
                    name + f"-deck-{level}",
                    [x0 + 0.07, y0 + 0.08, h + 0.09],
                    [x1 - 0.07, y1 - 0.08, h + 0.13],
                    [139, 124, 101],
                )
                for col in range(3):
                    if name == "bay-B-02" and level == 0 and col == 1:
                        continue
                    x = x0 + 0.18 + col * (x1 - x0 - 0.32) / 3
                    misplaced = name == "bay-B-03" and level == 0 and col == 1
                    colour = [214, 75, 77] if misplaced else [181, 146, 99]
                    carton = f"{name}-carton-{level}-{col}" + (
                        "-misplaced" if misplaced else ""
                    )
                    box(
                        carton,
                        [x, y0 + 0.16, h + 0.13],
                        [x + 0.57, y1 - 0.15, h + 0.87],
                        colour,
                    )
                    box(
                        carton + "-label",
                        [x + 0.15, y0 + 0.153, h + 0.38],
                        [x + 0.41, y0 + 0.16, h + 0.55],
                        [235, 235, 218],
                    )
    out.mkdir(parents=True, exist_ok=True)
    # GLB retains Z-up metric twin coordinates; dashboard loader must not rotate twice.
    scene.export(str(out / "scene.glb"))
    return export_cloud(
        np.concatenate(samples),
        out,
        "boxes",
        extra={
            "units": "metres",
            "up_axis": "Z",
            "site_id": site["site_id"],
            "synthetic": True,
            "colour_encoding": "linear RGB normalized 0..1",
            "objects": objects,
            "planted_issues": [
                {"zone_id": "bay-B-02", "issue": "empty", "level": 0, "column": 1},
                {"zone_id": "bay-B-03", "issue": "misplaced", "level": 0, "column": 1},
            ],
            "licence": "Procedural geometry; no external assets used.",
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=ROOT / "config/site.yaml")
    parser.add_argument("--out", type=Path, default=ROOT / "twin/out")
    args = parser.parse_args()
    metadata = generate(yaml.safe_load(args.site.read_text()), args.out)
    print(f"Generated {metadata['point_count']} points and scene.glb in {args.out}")


if __name__ == "__main__":
    main()
