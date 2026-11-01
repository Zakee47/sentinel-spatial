"""Load config/site.yaml (single source of truth for geometry and thresholds)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_YAML = REPO_ROOT / "config" / "site.yaml"


@lru_cache(maxsize=4)
def load_site(path: str | None = None) -> dict[str, Any]:
    with open(path or SITE_YAML) as f:
        return yaml.safe_load(f)


def bays(site: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {z["id"]: z for z in site["zones"] if z.get("kind") == "rack_bay"}


def bay_centre(zone: dict[str, Any]) -> tuple[float, float]:
    xs = [p[0] for p in zone["polygon_xy"]]
    ys = [p[1] for p in zone["polygon_xy"]]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def inspect_point(site: dict[str, Any], bay_id: str) -> tuple[float, float, float]:
    """Hover point in front of a bay: x = bay centre, y = bay front - standoff, z = patrol alt."""
    zone = bays(site)[bay_id]
    cx, _ = bay_centre(zone)
    front_y = min(p[1] for p in zone["polygon_xy"])
    d = site["drone"]
    return (cx, front_y - d["patrol_standoff_m"], d["patrol_altitude_m"])
