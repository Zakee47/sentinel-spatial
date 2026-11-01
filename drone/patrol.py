"""Patrol state machine: IDLE -> TAKEOFF -> GOTO_BAY -> INSPECT -> DECIDE -> ... -> RETURN -> LAND.

`Patrol.tick(now)` is called by the flight loop (10-30 Hz). It does ZERO network I/O: it reads
the Link snapshot (stop flag, mission, people) and the DecisionWorker result, sends supervised
velocity commands to the flight driver, and appends events/tasks to the Link outbox.
HOLD is entered when a decision times out (decision_timeout_s) or a person is too close.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from drone.api import Link
from drone.decide import BayVerdict, DecisionWorker
from drone.driver import DroneDriver, Frame
from drone.safety import Command, SafetySupervisor
from drone.site import bay_centre, bays, inspect_point

log = logging.getLogger("drone.patrol")
TASK_KIND = {"empty": "restock", "low_stock": "restock", "misplaced": "move", "label_issue": "fix_label",
             "obstruction": "hazard", "other": "review"}
ARRIVE_M = 0.15
KP = 1.2
HOLD_MAX_S = 8.0


def iso_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class PatrolLogEntry:
    t: float
    state: str
    x: float
    y: float
    z: float
    yaw: float
    battery: float
    cmd: tuple[float, float, float, float]
    safety: str
    reasons: list[str]
    bay: str | None


@dataclass
class Patrol:
    flight: DroneDriver
    supervisor: SafetySupervisor
    site: dict[str, Any]
    link: Link
    worker: DecisionWorker
    camera: DroneDriver | None = None  # frame source (live feed); defaults to `flight`
    mode: str = "sim"
    state: str = "IDLE"
    mission: dict[str, Any] | None = None
    bay_queue: list[str] = field(default_factory=list)
    current_bay: str | None = None
    last_decision: dict[str, Any] | None = None
    verdicts: list[BayVerdict] = field(default_factory=list)
    log: list[PatrolLogEntry] = field(default_factory=list)
    done_missions: set[str] = field(default_factory=set)
    _hold_from: str | None = None
    _hold_reason: str | None = None
    _hold_t0: float = 0.0
    _deadline: float = 0.0
    _rescans_left: int = 1
    _target: tuple[float, float, float] | None = None
    _inspect_frame: Frame | None = None
    _landing_reason: str | None = None
    _cam_tel: Any = None
    _cam_tel_t: float = 0.0

    def __post_init__(self) -> None:
        self.camera = self.camera or self.flight
        self.timeout_s = float(self.site["thresholds"]["decision_timeout_s"])
        d = self.site["drone"]
        self.home = (float(d["home_xy"][0]), float(d["home_xy"][1]), float(d["patrol_altitude_m"]))

    # ------------------------------------------------------------------------------------
    def tick(self, now: float) -> None:
        tel = self.flight.telemetry()
        snap = self.link.snapshot()
        cmd = self._behaviour(now, tel, snap)
        res = self.supervisor.check(cmd, tel, now, people_xy=snap.people_xy,
                                    stop_requested=snap.stop_requested, link_down_s=snap.link_down_s)
        if res.action == "land" and self.state not in ("LAND", "IDLE"):
            self._landing_reason = res.reasons[0]
            self._transition("LAND", reason=res.reasons[0])
            self.flight.land()
        elif res.action == "hold" and self.state not in ("HOLD", "IDLE", "LAND"):
            self._enter_hold(now, res.reasons[0])
        if res.action != "land" or self.state == "LAND":
            self.flight.send_velocity(res.command.vx, res.command.vy, res.command.vz, res.command.yaw_rate)
        self.log.append(PatrolLogEntry(now, self.state, tel.x, tel.y, tel.z, tel.yaw_deg, tel.battery_pct,
                                       (res.command.vx, res.command.vy, res.command.vz, res.command.yaw_rate),
                                       res.action, res.reasons, self.current_bay))
        self.link.publish_state(self.drone_state(self._display_tel(tel, now), snap.stop_requested))

    def _display_tel(self, tel: Any, now: float) -> Any:
        """Live mode: show the portal PnP fix when a portal is visible, else the sim estimate."""
        if self.camera is self.flight or self.camera is None:
            return tel
        if now - self._cam_tel_t > 0.25:
            self._cam_tel_t = now
            try:
                self._cam_tel = self.camera.telemetry()
            except Exception as e:  # noqa: BLE001 - never let the feed break the loop
                log.debug("camera telemetry failed: %s", e)
                self._cam_tel = None
        ct = self._cam_tel
        if ct is not None and ct.has_fix and ct.fix_source == "portal":
            return ct
        tel.fix_source = "estimate"
        return tel

    def _behaviour(self, now: float, tel: Any, snap: Any) -> Command:
        s = self.state
        if s == "IDLE":
            m = snap.mission
            if m and m.get("mission_id") not in self.done_missions and not snap.stop_requested:
                self._start_mission(m, tel)
            return Command()
        if s == "TAKEOFF":
            if tel.z >= self.home[2] - 0.1:
                self._next_bay()
            return self._goto((tel.x, tel.y, self.home[2]), tel)
        if s == "GOTO_BAY":
            assert self._target is not None
            if self._arrived(tel, self._target):
                self._transition("INSPECT")
            return self._goto(self._target, tel)
        if s == "INSPECT":
            frame = self.camera.latest_frame() if self.camera else None
            if frame is None:
                return self._hover(tel)
            self._inspect_frame = frame
            ref = getattr(self.flight, "reference_jpeg", None)
            self.worker.submit(self.current_bay, frame.jpeg(), ref(self.current_bay) if ref else None,
                               self._patrol_state(tel), truth=frame.meta.get("truth"))
            self._deadline = now + self.timeout_s
            self._transition("DECIDE")
            return self._hover(tel)
        if s == "DECIDE":
            r = self.worker.result()
            if r is not None:
                self._handle_result(r, tel)
            elif now > self._deadline:
                self._emit_patrol("HOLD", extra={"reason": "decision_timeout", "decision": "unclear"})
                self._enter_hold(now, "decision_timeout")
            return self._hover(tel)
        if s == "HOLD":
            if self._hold_reason == "decision_timeout":
                r = self.worker.result()
                if r is not None:
                    self.state = "DECIDE"
                    self._handle_result(r, tel)
                elif now - self._hold_t0 > HOLD_MAX_S:
                    self.worker.clear()
                    self._record_unclear(tel)
                    self._next_bay()
            elif snap.people_xy is not None and now - self._hold_t0 > 0.5:
                # people hold: resume once the supervisor no longer reports a hold
                if self.supervisor.check(Command(), tel, now, people_xy=snap.people_xy).action != "hold":
                    self._transition(self._hold_from or "RETURN", reason="clear")
            return Command()
        if s == "RETURN":
            if self._arrived(tel, self.home):
                self._transition("LAND")
                self.flight.land()
            return self._goto(self.home, tel)
        if s == "LAND":
            if not tel.airborne:
                if self.mission:
                    self.done_missions.add(self.mission.get("mission_id"))
                self.mission, self.current_bay = None, None
                self._transition("IDLE")
            return Command()
        return Command()

    # ------------------------------------------------------------------------------------
    def _start_mission(self, m: dict[str, Any], tel: Any) -> None:
        ok, why = self.supervisor.validate_mission(list(m.get("bays") or []), self.site)
        if not ok:
            log.warning("mission %s rejected: %s", m.get("mission_id"), why)
            self.done_missions.add(m.get("mission_id"))
            self._emit_patrol("IDLE", extra={"rejected_reason": why, "mission_id": m.get("mission_id")})
            return
        self.mission = m
        self.bay_queue = list(m["bays"])
        self.verdicts = []
        self.flight.takeoff()
        self._transition("TAKEOFF")

    def _next_bay(self) -> None:
        self._rescans_left = 1
        if not self.bay_queue:
            self.current_bay = None
            self._transition("RETURN")
            return
        self.current_bay = self.bay_queue.pop(0)
        self._target = inspect_point(self.site, self.current_bay)
        self._transition("GOTO_BAY")

    def _handle_result(self, r: BayVerdict | Exception, tel: Any) -> None:
        self.worker.clear()
        if isinstance(r, Exception):
            log.warning("decision failed: %s", r)
            self._record_unclear(tel)
            self._next_bay()
            return
        self.verdicts.append(r)
        self.last_decision = {"bay": r.bay_id, "issue": r.issue, "severity": r.severity,
                              "next_action": r.next_action, "confidence": r.confidence, "policy": r.policy,
                              "latency_s": round(r.latency_s, 3), "sim_truth": r.sim_truth_used}
        bx, by = bay_centre(bays(self.site)[r.bay_id])
        if r.issue not in ("ok", "unclear"):
            ev = self._event(r.bay_id, "bay_issue", (bx, by, self.home[2]), decision=r.decision,
                             confidence=r.confidence, payload={"issue": r.issue, "severity": r.severity})
            kind = TASK_KIND.get(r.issue)
            task = None
            if kind and r.severity != "none":
                task = {"zone_id": r.bay_id, "kind": kind, "severity": r.severity_score,
                        "note": f"Drone patrol: {r.issue} at {r.bay_id} ({r.severity})"}
            self.link.outbox.put({"event": ev, "task": task})
        self._emit_patrol("DECIDE", extra={"result": r.issue, "next_action": r.next_action})
        closer = None
        if self._target:
            closer = (self._target[0], self._target[1] + 0.5, self._target[2])
        action, why = self.supervisor.validate_action(r.next_action, tel, closer_target=closer,
                                                      rescans_left=self._rescans_left)
        if why:
            log.info("advisory action %s -> %s (%s)", r.next_action, action, why)
        if action in ("move_closer", "rescan"):
            self._rescans_left -= 1
            if action == "move_closer" and closer:
                self._target = closer
            self._transition("GOTO_BAY", reason=action)
        elif action == "return_home":
            self.bay_queue = []
            self._next_bay()
        elif action == "abort":
            self._transition("LAND", reason="abort")
            self.flight.land()
        else:
            self._next_bay()

    def _record_unclear(self, tel: Any) -> None:
        self.last_decision = {"bay": self.current_bay, "issue": "unclear", "policy": "unclear"}
        self._emit_patrol("DECIDE", extra={"result": "unclear"})

    def _enter_hold(self, now: float, reason: str) -> None:
        self._hold_from = self.state if self.state != "DECIDE" else "GOTO_BAY"
        self._hold_reason = reason
        self._hold_t0 = now
        self._transition("HOLD", reason=reason)

    def _transition(self, new: str, reason: str | None = None) -> None:
        if new == self.state:
            return
        log.info("%s -> %s%s%s", self.state, new, f" [{self.current_bay}]" if self.current_bay else "",
                 f" ({reason})" if reason else "")
        self.state = new
        if new != "IDLE" or reason:
            self._emit_patrol(new, extra={"reason": reason} if reason else None)

    # ------------------------------------------------------------------------------------
    def _goto(self, target: tuple[float, float, float], tel: Any) -> Command:
        dx, dy, dz = target[0] - tel.x, target[1] - tel.y, target[2] - tel.z
        yaw_err = ((90.0 - tel.yaw_deg + 180) % 360) - 180  # face the racking (+Y)
        return Command(KP * dx, KP * dy, KP * dz, 2.0 * yaw_err)

    def _hover(self, tel: Any) -> Command:
        return self._goto(self._target or (tel.x, tel.y, tel.z), tel)

    @staticmethod
    def _arrived(tel: Any, target: tuple[float, float, float]) -> bool:
        return math.dist((tel.x, tel.y, tel.z), target) < ARRIVE_M and math.hypot(tel.vx, tel.vy) < 0.2

    def _patrol_state(self, tel: Any) -> dict[str, Any]:
        return {"state": self.state, "bays_left": list(self.bay_queue), "battery_pct": round(tel.battery_pct, 1),
                "x": round(tel.x, 2), "y": round(tel.y, 2), "z": round(tel.z, 2),
                "rescans_left": self._rescans_left}

    def _event(self, zone_id: str, etype: str, xyz: tuple[float, float, float], **kw: Any) -> dict[str, Any]:
        return {"ts": iso_now(), "site_id": self.site["site_id"], "zone_id": zone_id, "type": etype,
                "x": round(xyz[0], 3), "y": round(xyz[1], 3), "z": round(xyz[2], 3), "source": "drone-1",
                "product_id": None, "track_id": None, "decision": kw.get("decision"),
                "confidence": kw.get("confidence"), "crop_ref": None, "payload": kw.get("payload") or {}}

    def _emit_patrol(self, state: str, extra: dict[str, Any] | None = None) -> None:
        tel = self.flight.telemetry()
        payload = {"state": state, "bay": self.current_bay, "mission_id": (self.mission or {}).get("mission_id"),
                   **(extra or {})}
        ev = self._event(self.current_bay or self._nearest_bay(tel.x), "patrol", (tel.x, tel.y, tel.z), payload=payload)
        self.link.outbox.put({"event": ev, "task": None})

    def _nearest_bay(self, x: float) -> str:
        return min(bays(self.site), key=lambda b: abs(bay_centre(bays(self.site)[b])[0] - x))

    def drone_state(self, tel: Any, stop_requested: bool) -> dict[str, Any]:
        return {"ts": iso_now(), "mode": self.mode, "state": self.state, "x": round(tel.x, 3), "y": round(tel.y, 3),
                "z": round(tel.z, 3), "yaw_deg": round(tel.yaw_deg, 1), "battery_pct": round(tel.battery_pct, 1),
                "current_bay": self.current_bay, "last_decision": self.last_decision,
                "stop_requested": stop_requested, "mission_id": (self.mission or {}).get("mission_id"),
                "feed_url": getattr(self.camera, "feed_url", None), "fix_source": tel.fix_source}
