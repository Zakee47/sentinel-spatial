"""Pure analytics over events: heatmap, funnel, summary text. No DB access (easy to unit test)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

FUNNEL_STAGES = ("pass_by", "look", "interest", "pick_up", "put_back", "kept")
_STAGE_KEY = {
    "pass_by": "passed_by",
    "look": "looked",
    "interest": "interested",
    "pick_up": "picked_up",
    "put_back": "put_back",
    "kept": "kept",
}
MAX_POINTS = 2000


def _duration(ev: dict[str, Any]) -> float:
    payload = ev.get("payload") or {}
    try:
        return float(payload.get("duration_s") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def heatmap(events: list[dict[str, Any]]) -> dict[str, Any]:
    """zones: per-zone summed look seconds and look count; points: [x, y, z, weight]."""
    zones: dict[str, dict[str, float]] = {}
    points: list[list[float]] = []
    for ev in events:
        if ev.get("type") not in ("look", "interest"):
            continue
        zid = ev.get("zone_id")
        dur = _duration(ev)
        z = zones.setdefault(zid, {"look_s": 0.0, "looks": 0})
        if ev["type"] == "look":
            z["look_s"] = round(z["look_s"] + dur, 2)
            z["looks"] += 1
        hit = (ev.get("payload") or {}).get("gaze_hit_xyz")
        if hit and len(hit) == 3:
            points.append(
                [float(hit[0]), float(hit[1]), float(hit[2]), round(max(dur, 0.1), 2)]
            )
        elif ev.get("x") is not None and ev.get("y") is not None:
            points.append(
                [
                    float(ev["x"]),
                    float(ev["y"]),
                    float(ev.get("z") or 0.0),
                    round(max(dur, 0.1), 2),
                ]
            )
    return {"zones": zones, "points": points[-MAX_POINTS:]}


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def funnel(
    products: list[dict[str, Any]], events: list[dict[str, Any]], sold: dict[str, int]
) -> list[dict[str, Any]]:
    """Per-product funnel. An event counts for a product if it names the product, or names no
    product but happened in the product's zone (e.g. a pass_by along the shelf).

    Flag rule: looked in the top quartile AND kept+sold in the bottom quartile (and looked > 0).
    """
    by_zone: dict[str, list[str]] = defaultdict(list)
    for p in products:
        by_zone[p["zone_id"]].append(p["product_id"])
    counts: dict[str, dict[str, int]] = {
        p["product_id"]: dict.fromkeys(_STAGE_KEY.values(), 0) for p in products
    }
    for ev in events:
        key = _STAGE_KEY.get(ev.get("type", ""))
        if key is None:
            continue
        pid = ev.get("product_id")
        targets = [pid] if pid else by_zone.get(ev.get("zone_id", ""), [])
        for t in targets:
            if t in counts:
                counts[t][key] += 1

    rows = []
    for p in products:
        c = counts[p["product_id"]]
        rows.append(
            {
                "product_id": p["product_id"],
                "name": p["name"],
                "zone_id": p["zone_id"],
                **c,
                "sold": int(sold.get(p["product_id"], 0)),
                "put_back_rate": round(c["put_back"] / c["picked_up"], 3)
                if c["picked_up"]
                else 0.0,
                "flag_high_attention_low_conversion": False,
            }
        )
    looks_q3 = _quantile([r["looked"] for r in rows], 0.75)
    conv_q1 = _quantile([r["kept"] + r["sold"] for r in rows], 0.25)
    for r in rows:
        r["flag_high_attention_low_conversion"] = bool(
            r["looked"] > 0
            and r["looked"] >= looks_q3
            and (r["kept"] + r["sold"]) <= conv_q1
        )
    return rows


def zone_rollup(funnel_rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    zones: dict[str, dict[str, float]] = {}
    for r in funnel_rows:
        z = zones.setdefault(
            r["zone_id"],
            {"looked": 0, "kept": 0, "sold": 0, "picked_up": 0, "put_back": 0},
        )
        for k in z:
            z[k] += r[k]
    for z in zones.values():
        z["conversion"] = (
            round((z["kept"] + z["sold"]) / z["looked"], 3) if z["looked"] else 0.0
        )
    return zones
