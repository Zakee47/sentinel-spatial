"""Load config/site.yaml into small typed helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_YAML = REPO_ROOT / "config" / "site.yaml"


@dataclass
class Zone:
    id: str
    kind: str
    polygon_xy: np.ndarray  # (N, 2)
    z_range: tuple[float, float]
    products: list[str] = field(default_factory=list)

    @property
    def box_min(self) -> np.ndarray:
        return np.array([*self.polygon_xy.min(axis=0), self.z_range[0]])

    @property
    def box_max(self) -> np.ndarray:
        return np.array([*self.polygon_xy.max(axis=0), self.z_range[1]])

    def corners(self) -> np.ndarray:
        lo, hi = self.box_min, self.box_max
        return np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])

    def contains_xy(self, x: float, y: float) -> bool:
        return point_in_polygon(x, y, self.polygon_xy)

    def product_at_x(self, x: float) -> str | None:
        if not self.products:
            return None
        lo, hi = self.box_min[0], self.box_max[0]
        i = int(np.clip((x - lo) / max(hi - lo, 1e-6) * len(self.products), 0, len(self.products) - 1))
        return self.products[i]


def point_in_polygon(x: float, y: float, poly: np.ndarray) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


@dataclass
class Site:
    raw: dict[str, Any]

    @property
    def site_id(self) -> str:
        return self.raw["site_id"]

    @property
    def floor_plane(self) -> np.ndarray:
        return np.array(self.raw.get("floor_plane", [0, 0, 1, 0]), dtype=float)

    @property
    def thresholds(self) -> dict[str, Any]:
        return self.raw["thresholds"]

    @property
    def zones(self) -> list[Zone]:
        return [
            Zone(z["id"], z["kind"], np.array(z["polygon_xy"], float), tuple(z["z_range"]), z.get("products", []))
            for z in self.raw["zones"]
        ]

    def zones_of(self, kind: str) -> list[Zone]:
        return [z for z in self.zones if z.kind == kind]

    def portal(self, portal_id: str) -> dict[str, Any]:
        for p in self.raw["portals"]:
            if p["id"] == portal_id:
                return {"id": p["id"], "size_m": float(p["size_m"]), "T": np.array(p["T_twin_portal"], float).reshape(4, 4)}
        raise KeyError(portal_id)

    def camera(self, camera_id: str) -> dict[str, Any]:
        for c in self.raw["cameras"]:
            if c["id"] == camera_id:
                return c
        raise KeyError(camera_id)


def load_site(path: Path | str = SITE_YAML) -> Site:
    with open(path) as f:
        return Site(yaml.safe_load(f))
