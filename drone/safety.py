"""Code safety supervisor. Every velocity command and every advisory action passes through here.

It sits ON TOP of DJI's own safety systems (obstacle sensing, geofence, RTH), never in place of
them. Pure functions, no I/O, no network: safe to call from the flight loop.

Rule precedence (first match wins for LAND/HOLD; clamps compose):
  1. STOP requested from the dashboard            -> LAND (latched)
  2. battery < min_battery_pct                    -> LAND (latched)
  3. no position fix for > lost_fix_land_s        -> LAND (latched)
  4. lost link to the server for > lost_link_land_s (after it was up) -> LAND (latched)
  5. outside the geofence polygon                 -> LAND (latched)
  6. a person within min_dist_people_m            -> HOLD (zero velocity, not latched)
  7. command would leave the geofence             -> horizontal velocity zeroed (clamp)
  8. command would exceed max_alt_m               -> vz clamped (clamp)
  9. speed > max_speed_mps                        -> scaled down (clamp)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from drone.driver import Telemetry

Action = Literal["ok", "clamp", "hold", "land"]
MAX_YAW_RATE_DPS = 90.0


@dataclass
class Command:
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    yaw_rate: float = 0.0


@dataclass
class SafetyResult:
    action: Action
    command: Command
    reasons: list[str] = field(default_factory=list)


def point_in_polygon(x: float, y: float, poly: list[list[float]]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


class SafetySupervisor:
    def __init__(self, drone_cfg: dict[str, Any], lookahead_s: float = 0.5,
                 lost_link_land_s: float = 5.0) -> None:
        self.fence: list[list[float]] = drone_cfg["geofence_polygon_xy"]
        self.max_alt = float(drone_cfg["max_alt_m"])
        self.max_speed = float(drone_cfg["max_speed_mps"])
        self.min_battery = float(drone_cfg["min_battery_pct"])
        self.min_dist_people = float(drone_cfg["min_dist_people_m"])
        self.lost_fix_land_s = float(drone_cfg["lost_fix_land_s"])
        self.lost_link_land_s = lost_link_land_s
        self.lookahead_s = lookahead_s
        self.land_latched: str | None = None

    # ---- flight-loop check -------------------------------------------------------------
    def check(self, cmd: Command, tel: Telemetry, now: float, *,
              people_xy: list[tuple[float, float]] | None = None,
              stop_requested: bool = False, link_down_s: float = 0.0) -> SafetyResult:
        land_reason = self._land_reason(tel, now, stop_requested, link_down_s)
        if land_reason and self.land_latched is None:
            self.land_latched = land_reason
        if self.land_latched:
            return SafetyResult("land", Command(), [self.land_latched])

        for px, py in people_xy or []:
            d = math.hypot(px - tel.x, py - tel.y)
            if d < self.min_dist_people:
                return SafetyResult("hold", Command(), [f"person {d:.1f} m < {self.min_dist_people} m"])

        out = Command(cmd.vx, cmd.vy, cmd.vz, cmd.yaw_rate)
        reasons: list[str] = []
        # speed clamp (horizontal and vertical)
        h = math.hypot(out.vx, out.vy)
        if h > self.max_speed:
            k = self.max_speed / h
            out.vx, out.vy = out.vx * k, out.vy * k
            reasons.append(f"speed {h:.2f} > {self.max_speed} m/s")
        if abs(out.vz) > self.max_speed:
            out.vz = math.copysign(self.max_speed, out.vz)
            reasons.append("vertical speed clamped")
        if abs(out.yaw_rate) > MAX_YAW_RATE_DPS:
            out.yaw_rate = math.copysign(MAX_YAW_RATE_DPS, out.yaw_rate)
            reasons.append("yaw rate clamped")
        # geofence look-ahead
        nx, ny = tel.x + out.vx * self.lookahead_s, tel.y + out.vy * self.lookahead_s
        if (out.vx or out.vy) and not point_in_polygon(nx, ny, self.fence):
            out.vx = out.vy = 0.0
            reasons.append("would leave geofence")
        # altitude ceiling look-ahead
        if tel.z + out.vz * self.lookahead_s > self.max_alt and out.vz > 0:
            out.vz = 0.0
            reasons.append(f"would exceed max_alt {self.max_alt} m")
        return SafetyResult("clamp" if reasons else "ok", out, reasons)

    def _land_reason(self, tel: Telemetry, now: float, stop_requested: bool,
                     link_down_s: float) -> str | None:
        if stop_requested:
            return "STOP requested"
        if tel.battery_pct < self.min_battery:
            return f"battery {tel.battery_pct:.0f}% < {self.min_battery:.0f}%"
        if not tel.has_fix and now - tel.last_fix_ts > self.lost_fix_land_s:
            return f"lost position fix > {self.lost_fix_land_s} s"
        if link_down_s > self.lost_link_land_s:
            return f"lost link > {self.lost_link_land_s} s"
        if tel.airborne and tel.has_fix and not point_in_polygon(tel.x, tel.y, self.fence):
            return "outside geofence"
        if tel.z > self.max_alt + 0.5:
            return f"altitude {tel.z:.1f} m > max_alt"
        return None

    # ---- planning-time checks (missions, waypoints, advisory actions) ------------------
    def validate_target(self, x: float, y: float, z: float) -> tuple[bool, str | None]:
        if not point_in_polygon(x, y, self.fence):
            return False, f"target ({x:.2f},{y:.2f}) outside geofence"
        if z > self.max_alt:
            return False, f"target altitude {z:.1f} > max_alt {self.max_alt}"
        return True, None

    def validate_mission(self, bay_ids: list[str], site: dict[str, Any]) -> tuple[bool, str | None]:
        from drone.site import bays, inspect_point

        known = bays(site)
        if not bay_ids:
            return False, "empty mission"
        for b in bay_ids:
            if b not in known:
                return False, f"unknown bay {b}"
            ok, why = self.validate_target(*inspect_point(site, b))
            if not ok:
                return False, f"{b}: {why}"
        return True, None

    def validate_action(self, action: str, tel: Telemetry, *, closer_target: tuple[float, float, float] | None = None,
                        rescans_left: int = 1) -> tuple[str, str | None]:
        """Map an advisory drone_next_action to the action the flight loop may execute."""
        if self.land_latched:
            return "abort", self.land_latched
        if tel.battery_pct < self.min_battery + 10 and action in ("next_bay", "flag_and_continue",
                                                                   "move_closer", "rescan"):
            return "return_home", "battery low: returning instead of continuing"
        if action in ("move_closer", "rescan"):
            if rescans_left <= 0:
                return "next_bay", "rescan budget used"
            if action == "move_closer" and closer_target is not None:
                ok, why = self.validate_target(*closer_target)
                if not ok:
                    return "rescan", why
        if action not in ("next_bay", "move_closer", "rescan", "flag_and_continue", "return_home", "abort"):
            return "return_home", f"unknown action {action!r}"
        return action, None
