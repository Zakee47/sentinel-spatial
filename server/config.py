"""Pydantic model for config/site.yaml (the single source of truth for geometry/thresholds)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_PATH = Path(os.environ.get("SENTINEL_SITE", REPO_ROOT / "config" / "site.yaml"))
SCHEMA_PATH = REPO_ROOT / "db" / "schema.sql"


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class Portal(_Open):
    id: str
    size_m: float
    T_twin_portal: list[float]


class Camera(_Open):
    id: str
    kind: str
    url: str | None = None
    fps: float | None = None


class Zone(_Open):
    id: str
    kind: str
    polygon_xy: list[list[float]]
    z_range: list[float]
    products: list[str] = []
    reference_image: str | None = None

    @property
    def centre(self) -> tuple[float, float]:
        xs = [p[0] for p in self.polygon_xy]
        ys = [p[1] for p in self.polygon_xy]
        return (sum(xs) / len(xs), sum(ys) / len(ys))


class Drone(_Open):
    home_xy: list[float]
    patrol_altitude_m: float
    patrol_standoff_m: float
    geofence_polygon_xy: list[list[float]]
    max_alt_m: float
    max_speed_mps: float
    min_battery_pct: float
    min_dist_people_m: float
    lost_fix_land_s: float


class Site(_Open):
    site_id: str
    units: str
    floor_plane: list[float]
    portals: list[Portal]
    cameras: list[Camera]
    zones: list[Zone]
    thresholds: dict[str, Any]
    drone: Drone

    def zone(self, zone_id: str) -> Zone | None:
        return next((z for z in self.zones if z.id == zone_id), None)

    def zones_of(self, kind: str) -> list[Zone]:
        return [z for z in self.zones if z.kind == kind]

    def product_zone(self, product_id: str) -> str | None:
        return next((z.id for z in self.zones if product_id in z.products), None)


@lru_cache
def raw_site() -> dict[str, Any]:
    return yaml.safe_load(SITE_PATH.read_text())


@lru_cache
def load_site() -> Site:
    return Site.model_validate(raw_site())
