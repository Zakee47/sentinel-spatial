"""Render a composite (top-down twin map + drone camera view) for GIFs / previews."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from drone.site import bays

SCALE = 52  # px per metre
X0, Y0 = -1.0, 2.5  # map origin (metres)
MAP_W, MAP_H = int(12 * SCALE), int(7.5 * SCALE)
ISSUE_COL = {"ok": (90, 200, 90), "empty": (60, 60, 230), "misplaced": (40, 160, 255), "unclear": (180, 180, 180)}


def _px(x: float, y: float) -> tuple[int, int]:
    return int((x - X0) * SCALE), int(MAP_H - (y - Y0) * SCALE)


def render_map(site: dict[str, Any], path: list[tuple[float, float]], st: dict[str, Any],
               findings: dict[str, str]) -> np.ndarray:
    img = np.full((MAP_H, MAP_W, 3), (32, 28, 26), np.uint8)
    fence = np.array([_px(*p) for p in site["drone"]["geofence_polygon_xy"]], np.int32)
    cv2.polylines(img, [fence], True, (80, 200, 255), 1, cv2.LINE_AA)
    cv2.putText(img, "geofence", (fence[0][0] + 4, fence[0][1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (80, 200, 255), 1)
    for bid, z in bays(site).items():
        poly = np.array([_px(*p) for p in z["polygon_xy"]], np.int32)
        col = ISSUE_COL.get(findings.get(bid, ""), (120, 120, 120))
        cv2.fillPoly(img, [poly], tuple(int(c * 0.45) for c in col))
        cv2.polylines(img, [poly], True, col, 2)
        cv2.putText(img, bid[-4:] + (f" {findings[bid]}" if bid in findings else ""), (poly[0][0] + 6, poly[2][1] + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (240, 240, 240), 1, cv2.LINE_AA)
    hx, hy = site["drone"]["home_xy"]
    cv2.drawMarker(img, _px(hx, hy), (200, 200, 200), cv2.MARKER_SQUARE, 14, 1)
    cv2.putText(img, "home", _px(hx + 0.2, hy - 0.3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
    if len(path) > 1:
        cv2.polylines(img, [np.array([_px(*p) for p in path], np.int32)], False, (255, 160, 60), 2, cv2.LINE_AA)
    x, y = st["x"], st["y"]
    cv2.circle(img, _px(x, y), 8, (255, 255, 255), -1)
    yaw = np.radians(st["yaw_deg"])
    tip = _px(x + 0.6 * np.cos(yaw), y + 0.6 * np.sin(yaw))
    cv2.line(img, _px(x, y), tip, (255, 255, 255), 2)
    lines = [f"{st['mode'].upper()}  {st['state']}  bay={st['current_bay'] or '-'}",
             f"x={x:.2f} y={y:.2f} z={st['z']:.2f}  batt={st['battery_pct']:.0f}%  fix={st.get('fix_source')}"]
    for i, t in enumerate(lines):
        cv2.putText(img, t, (10, MAP_H - 34 + 20 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def compose(map_img: np.ndarray, cam: np.ndarray | None, caption: str) -> np.ndarray:
    h = map_img.shape[0]
    if cam is None:
        cam = np.zeros((480, 640, 3), np.uint8)
    cam = cv2.resize(cam, (int(cam.shape[1] * h / cam.shape[0]), h))
    cv2.rectangle(cam, (0, h - 28), (cam.shape[1], h), (0, 0, 0), -1)
    cv2.putText(cam, caption, (8, h - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return np.hstack([map_img, cam])
