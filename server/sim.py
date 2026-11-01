"""Simulated floor + simulated drone patrol, posting to the Sentinel server over REST.

    python -m server.sim                      # floor + drone, forever
    python -m server.sim --duration 180       # stop after 3 minutes
    python -m server.sim --no-drone           # floor only (when drone/ pushes real state)

Floor: shoppers walk the aisle floor and emit pass_by / look / interest / pick_up / put_back / kept
with confidences and decision objects. SKU-007 is planted as "high attention, low conversion".
Drone: a pure-software patrol (no real aircraft) posting DroneState at 2 Hz; bay-B-02 is empty and
bay-B-03 has a misplaced carton. It honours missions from GET /api/drone/mission and stop_requested.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import random
import time
from typing import Any

import httpx

from .config import load_site
from .seed import LOW_CONVERSION_SKU

TICK_S = 0.5  # 2 Hz drone state
BAY_FINDINGS = {
    "bay-B-02": ("empty", "act_now", "restock", 3.0, "Pick face empty — restock"),
    "bay-B-03": (
        "misplaced",
        "act_today",
        "move",
        2.0,
        "Misplaced carton — move to correct bay",
    ),
}


def _policy(question: str, conf: float) -> str:
    th = load_site().thresholds.get(question, {"auto": 0.85, "review": 0.55})
    return (
        "auto" if conf >= th["auto"] else "review" if conf >= th["review"] else "ignore"
    )


def _decision(question: str, answer: dict[str, Any], conf: float) -> dict[str, Any]:
    return {"question": question, "answer": answer, "policy": _policy(question, conf)}


class Sim:
    def __init__(self, api: str, rng: random.Random) -> None:
        self.api = api.rstrip("/")
        self.http = httpx.AsyncClient(base_url=self.api, timeout=5.0)
        self.rng = rng
        self.site = load_site()
        self.shelves = sorted(
            self.site.zones_of("retail_shelf"), key=lambda z: z.polygon_xy[0][0]
        )
        self.track_n = 0

    async def post_event(self, ev: dict[str, Any]) -> str | None:
        ev.setdefault("site_id", self.site.site_id)
        ev.setdefault("source", "sim")
        try:
            r = await self.http.post("/api/events", json=ev)
            r.raise_for_status()
            return r.json()["event_ids"][0]
        except httpx.HTTPError as e:
            print(f"[sim] POST /api/events failed: {e}")
            return None

    # ---------------------------------------------------------------- floor
    def _product_xyz(self, zone, pid: str) -> list[float]:
        i = zone.products.index(pid)
        x0 = zone.polygon_xy[0][0]
        x1 = zone.polygon_xy[1][0]
        y_face = zone.polygon_xy[0][1]
        px = x0 + (i + 0.5) * (x1 - x0) / len(zone.products)
        pz = 0.5 + 0.25 * (i % 4) + self.rng.uniform(-0.08, 0.08)
        return [round(px + self.rng.uniform(-0.05, 0.05), 3), y_face, round(pz, 3)]

    async def shopper(self) -> None:
        self.track_n += 1
        tid = f"t{self.track_n}"
        rng = self.rng
        y = rng.uniform(1.0, 1.8)
        speed = rng.uniform(0.6, 1.1)
        reverse = rng.random() < 0.4
        shelves = list(reversed(self.shelves)) if reverse else self.shelves
        for zone in shelves:
            x0, x1 = zone.polygon_xy[0][0], zone.polygon_xy[1][0]
            x = rng.uniform(x0, x1)
            await asyncio.sleep((x1 - x0) / speed)
            await self.post_event(
                {
                    "zone_id": zone.id,
                    "type": "pass_by",
                    "x": round(x, 3),
                    "y": round(y, 3),
                    "z": 0.0,
                    "track_id": tid,
                    "source": "sim",
                    "confidence": round(rng.uniform(0.85, 0.99), 2),
                }
            )
            weights = [6.0 if p == LOW_CONVERSION_SKU else 1.0 for p in zone.products]
            if rng.random() > (0.75 if LOW_CONVERSION_SKU in zone.products else 0.45):
                continue
            pid = rng.choices(zone.products, weights=weights)[0]
            hot = pid == LOW_CONVERSION_SKU
            dur = round(rng.uniform(2.5, 8.0) if hot else rng.uniform(1.5, 5.5), 2)
            hit = self._product_xyz(zone, pid)
            await asyncio.sleep(min(dur, 3.0))
            conf = round(rng.uniform(0.7, 0.97), 2)
            await self.post_event(
                {
                    "zone_id": zone.id,
                    "type": "look",
                    "product_id": pid,
                    "x": round(x, 3),
                    "y": round(y, 3),
                    "z": 0.0,
                    "track_id": tid,
                    "confidence": conf,
                    "payload": {"duration_s": dur, "gaze_hit_xyz": hit},
                }
            )
            if dur >= self.site.thresholds["interest_min_s"]:
                await self.post_event(
                    {
                        "zone_id": zone.id,
                        "type": "interest",
                        "product_id": pid,
                        "x": round(x, 3),
                        "y": round(y, 3),
                        "z": 0.0,
                        "track_id": tid,
                        "confidence": conf,
                        "payload": {"duration_s": dur},
                    }
                )
            if rng.random() > (0.7 if hot else 0.5):
                continue
            hold_conf = round(rng.uniform(0.6, 0.99), 2)
            await self.post_event(
                {
                    "zone_id": zone.id,
                    "type": "pick_up",
                    "product_id": pid,
                    "x": round(x, 3),
                    "y": round(y, 3),
                    "z": 0.0,
                    "track_id": tid,
                    "confidence": hold_conf,
                    "crop_ref": f"crops/{tid}-{pid}-hand.jpg",
                    "decision": _decision(
                        "holding_product",
                        {"type": "predicate", "probability": hold_conf},
                        hold_conf,
                    ),
                }
            )
            await asyncio.sleep(rng.uniform(1.0, 3.0))
            back = rng.random() < (0.85 if hot else 0.3)
            out_conf = round(rng.uniform(0.5, 0.98), 2)
            await self.post_event(
                {
                    "zone_id": zone.id,
                    "type": "put_back" if back else "kept",
                    "product_id": pid,
                    "x": round(x, 3),
                    "y": round(y, 3),
                    "z": 0.0,
                    "track_id": tid,
                    "confidence": out_conf,
                    "crop_ref": f"crops/{tid}-{pid}-after.jpg",
                    "decision": _decision(
                        "reach_outcome",
                        {
                            "type": "choice",
                            "value": "back_on_shelf" if back else "in_basket",
                            "confidence": out_conf,
                        },
                        out_conf,
                    ),
                }
            )

    async def floor(self, mean_gap_s: float) -> None:
        tasks: set[asyncio.Task] = set()
        while True:
            t = asyncio.create_task(self.shopper())
            tasks.add(t)
            t.add_done_callback(tasks.discard)
            await asyncio.sleep(self.rng.expovariate(1.0 / mean_gap_s))

    # ---------------------------------------------------------------- drone
    async def drone(self) -> None:
        d = self.site.drone
        home = d.home_xy
        st: dict[str, Any] = {
            "mode": "sim",
            "state": "IDLE",
            "x": home[0],
            "y": home[1],
            "z": 0.0,
            "yaw_deg": 90.0,
            "battery_pct": 96.0,
            "current_bay": None,
            "last_decision": None,
            "stop_requested": False,
            "mission_id": None,
            "feed_url": None,
        }
        bays = {z.id: z for z in self.site.zones_of("rack_bay")}
        inspect_y = bays["bay-B-01"].polygon_xy[0][1] - d.patrol_standoff_m

        async def push() -> bool:
            """Post state; return True if the server asks us to stop."""
            st["battery_pct"] = round(
                max(st["battery_pct"] - (0.08 if st["z"] > 0 else 0.0), 0.0), 2
            )
            try:
                await self.http.post("/api/drone/state", json=st)
                srv = (await self.http.get("/api/drone/state")).json()
                return bool(srv.get("stop_requested"))
            except httpx.HTTPError as e:
                print(f"[sim] drone push failed: {e}")
                return False

        async def tick(state: str) -> bool:
            st["state"] = state
            stop = await push()
            await asyncio.sleep(TICK_S)
            return stop

        async def move_to(tx: float, ty: float, tz: float, state: str) -> bool:
            while True:
                dx, dy, dz = tx - st["x"], ty - st["y"], tz - st["z"]
                dist = math.sqrt(dx * dx + dy * dy + dz * dz)
                if dist < 0.05:
                    st["x"], st["y"], st["z"] = tx, ty, tz
                    return await tick(state)
                step = min(d.max_speed_mps * 0.8 * TICK_S, dist)
                st["x"] = round(st["x"] + dx / dist * step, 3)
                st["y"] = round(st["y"] + dy / dist * step, 3)
                st["z"] = round(st["z"] + dz / dist * step, 3)
                if abs(dx) + abs(dy) > 0.05:
                    st["yaw_deg"] = round(math.degrees(math.atan2(dy, dx)), 1)
                if await tick(state):
                    return True

        async def land() -> None:
            st["current_bay"] = None
            await move_to(st["x"], st["y"], 0.0, "LAND")

        while True:
            # IDLE: wait for a mission (or auto-patrol after a short pause), honour stop.
            st.update(state="IDLE", current_bay=None, mission_id=None)
            mission = None
            for _ in range(int(8 / TICK_S)):
                stop = await tick("IDLE")
                try:
                    mission = (await self.http.get("/api/drone/mission")).json()
                except httpx.HTTPError:
                    mission = None
                if mission:
                    break
                if stop:
                    continue
            if mission is None and stop:
                continue
            if st["battery_pct"] < d.min_battery_pct + 10:
                st["battery_pct"] = 100.0  # battery swap while idle on the pad
            route = mission["bays"] if mission else list(bays)
            st["mission_id"] = mission["mission_id"] if mission else None
            await self.post_event(
                {
                    "zone_id": route[0],
                    "type": "patrol",
                    "source": "drone-1",
                    "x": st["x"],
                    "y": st["y"],
                    "z": st["z"],
                    "payload": {
                        "state": "TAKEOFF",
                        "bay": route[0],
                        "mission_id": st["mission_id"],
                    },
                }
            )
            if await move_to(st["x"], st["y"], d.patrol_altitude_m, "TAKEOFF"):
                await land()
                continue
            aborted = False
            for bay_id in route:
                bay = bays[bay_id]
                cx, _ = bay.centre
                st["current_bay"] = bay_id
                if await move_to(cx, inspect_y, d.patrol_altitude_m, "GOTO_BAY"):
                    aborted = True
                    break
                st["yaw_deg"] = 90.0
                for _ in range(4):
                    if await tick("INSPECT"):
                        aborted = True
                        break
                if aborted:
                    break
                issue, severity, kind, sev_num, note = BAY_FINDINGS.get(
                    bay_id, ("ok", "none", None, 0.0, None)
                )
                conf = round(
                    self.rng.uniform(0.88, 0.97)
                    if issue != "ok"
                    else self.rng.uniform(0.9, 0.99),
                    2,
                )
                dec = _decision(
                    "bay_issue",
                    {"type": "choice", "value": issue, "confidence": conf},
                    conf,
                )
                st["last_decision"] = {
                    **dec,
                    "bay": bay_id,
                    "severity": severity,
                    "confidence": conf,
                }
                if await tick("DECIDE"):
                    aborted = True
                    break
                ev_id = await self.post_event(
                    {
                        "zone_id": bay_id,
                        "type": "bay_issue",
                        "source": "drone-1",
                        "x": cx,
                        "y": inspect_y,
                        "z": d.patrol_altitude_m,
                        "confidence": conf,
                        "decision": dec,
                        "crop_ref": f"crops/{bay_id}-{int(time.time())}.jpg",
                        "payload": {"issue": issue, "severity": severity},
                    }
                )
                if kind:
                    await self.ensure_task(bay_id, kind, sev_num, ev_id, note)
            await move_to(
                home[0],
                home[1],
                d.patrol_altitude_m if not aborted else st["z"],
                "RETURN",
            )
            await land()

    async def ensure_task(
        self,
        zone_id: str,
        kind: str,
        severity: float,
        ev_id: str | None,
        note: str | None,
    ) -> None:
        try:
            open_tasks = (
                await self.http.get("/api/tasks", params={"status": "open"})
            ).json()
            if any(t["zone_id"] == zone_id and t["kind"] == kind for t in open_tasks):
                return
            await self.http.post(
                "/api/tasks",
                json={
                    "zone_id": zone_id,
                    "kind": kind,
                    "severity": severity,
                    "source_event": ev_id,
                    "note": note,
                },
            )
        except httpx.HTTPError as e:
            print(f"[sim] task create failed: {e}")


async def main_async(args: argparse.Namespace) -> None:
    sim = Sim(args.api, random.Random(args.seed))
    jobs = []
    if not args.no_floor:
        jobs.append(sim.floor(args.shopper_gap))
    if not args.no_drone:
        jobs.append(sim.drone())
    print(
        f"[sim] posting to {args.api} (floor={not args.no_floor}, drone={not args.no_drone})"
    )
    try:
        await asyncio.wait_for(asyncio.gather(*jobs), timeout=args.duration or None)
    except TimeoutError:
        print("[sim] duration reached, stopping")
    finally:
        await sim.http.aclose()


def main() -> None:
    p = argparse.ArgumentParser(description="Sentinel simulated floor + drone")
    p.add_argument(
        "--api", default=os.environ.get("SENTINEL_API", "http://localhost:8000")
    )
    p.add_argument("--duration", type=float, default=0, help="seconds; 0 = forever")
    p.add_argument(
        "--shopper-gap",
        type=float,
        default=2.5,
        help="mean seconds between new shoppers",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--no-drone", action="store_true")
    p.add_argument("--no-floor", action="store_true")
    args = p.parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
