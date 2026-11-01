"""Run the drone stack.

    python -m drone.run --mode sim --mission bay-B-01,bay-B-02,bay-B-03,bay-B-04 --gif drone/out/patrol.gif
    python -m drone.run --mode sim                      # waits for GET /api/drone/mission
    python -m drone.run --mode live --source 10 --crop 0.1,0.08,0.8,0.84

Threads: flight loop (this thread, --hz, no network), network link (drone/api.py), decision
worker (drone/decide.py). In live mode the Neo 2 is human-piloted: video comes from
LiveFeedDriver; the position shown is the portal PnP fix when a portal is visible, otherwise the
simulated/estimated position (labelled fix_source=sim/estimate).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from drone.api import ApiClient, Link
from drone.decide import DecisionWorker
from drone.patrol import Patrol
from drone.recorder import FrameRecorder
from drone.safety import SafetySupervisor
from drone.sim import SimDriver
from drone.site import load_site

log = logging.getLogger("drone.run")
ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m drone.run")
    ap.add_argument("--mode", choices=["sim", "live"], default="sim")
    ap.add_argument("--source", default=None, help="live video: device index, rtmp://..., file, screen[:L,T,W,H]")
    ap.add_argument("--crop", default=None, help="live video crop x,y,w,h (px, or fractions <= 1)")
    ap.add_argument("--api", default=os.environ.get("SENTINEL_API", "http://localhost:8000"),
                    help="Sentinel server base URL, or 'none' for offline")
    ap.add_argument("--mission", default=None, help="comma-separated bays to patrol now (skips the server queue)")
    ap.add_argument("--hz", type=float, default=20.0, help="flight loop rate (10-30)")
    ap.add_argument("--max-s", "--max-seconds", dest="max_s", type=float, default=0.0,
                    help="exit after N seconds (0 = run forever)")
    ap.add_argument("--record", default=None, metavar="DIR", help="record sampled live frames under DIR")
    ap.add_argument("--record-every", type=float, default=0.5, help="record one live frame every N seconds")
    ap.add_argument("--build-twin-on-land", nargs="?", const="", default=None, metavar="SURVEY_JSON",
                    help="build a twin from --record frames when the live session ends")
    ap.add_argument("--once", action="store_true", help="exit after the first mission completes")
    ap.add_argument("--gif", default=None, help="write a patrol GIF (map + camera) here")
    ap.add_argument("--log", default="drone/out/patrol_log.jsonl", help="per-tick JSONL log")
    ap.add_argument("--people", default=None, help="sim: inject a person at x,y after T s: 'x,y@T'")
    ap.add_argument("--battery", type=float, default=100.0, help="sim: starting battery %%")
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
    if a.record and a.mode != "live":
        raise SystemExit("--record requires --mode live")
    if a.build_twin_on_land is not None and not a.record:
        raise SystemExit("--build-twin-on-land requires --record DIR")
    if a.record_every <= 0:
        raise SystemExit("--record-every must be positive")
    if a.build_twin_on_land and not Path(a.build_twin_on_land).is_file():
        raise SystemExit(f"Survey not found: {a.build_twin_on_land}")
    hz = min(30.0, max(10.0, a.hz))
    site = load_site()
    flight = SimDriver(site, battery_pct=a.battery)
    camera = None
    if a.mode == "live":
        from drone.live import LiveFeedDriver

        cam_cfg = next((c for c in site["cameras"] if c["id"] == "drone-1"), {})
        camera = LiveFeedDriver(a.source or str(cam_cfg.get("url", "0")), site, fps=float(cam_cfg.get("fps", 10)),
                                crop=a.crop)
    recorder = None
    record_dir = None
    if a.record:
        record_dir = Path(a.record).expanduser().resolve()
        source = camera.source if camera else str(a.source or "")
        recorder = FrameRecorder(record_dir, source, crop=a.crop, every_s=a.record_every)
    client = None if a.api == "none" else ApiClient(a.api)
    link = Link(client)
    link.start()
    if a.mission:
        link.inject_mission({"mission_id": f"local-{int(time.time())}", "bays": a.mission.split(","),
                             "reason": "cli", "requested_by": "user"})
    patrol = Patrol(flight, SafetySupervisor(site["drone"]), site, link, DecisionWorker(), camera=camera, mode=a.mode)
    people_at = None
    if a.people:
        xy, t = a.people.split("@")
        people_at = (tuple(float(v) for v in xy.split(",")), float(t))

    stop = {"flag": False, "reason": None}

    def request_stop(_signal: int, _frame: object) -> None:
        stop["flag"] = True
        stop["reason"] = "ctrl_c" if _signal == signal.SIGINT else "sigterm"

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    Path(a.log).parent.mkdir(parents=True, exist_ok=True)
    frames, path, findings = [], [], {}
    gif_every = max(1, int(hz / 4))
    period = 1.0 / hz
    t0 = last = time.monotonic()
    tick = 0
    started = False
    log.info("flight loop %.0f Hz, mode=%s, api=%s", hz, a.mode, a.api)
    end_reason = "session_ended"
    while not stop["flag"]:
        now = time.monotonic()
        flight.step(now - last)
        last = now
        if people_at and now - t0 > people_at[1]:
            link.set_people([people_at[0]])
            if now - t0 > people_at[1] + 4:
                link.set_people([])
                people_at = None
        previous_state = patrol.state
        patrol.tick(now)  # no network in here
        started = started or patrol.state != "IDLE"
        if recorder and camera:
            frame = camera.latest_frame()
            if frame is not None:
                recorder.offer(frame)
        tick += 1
        if a.gif and tick % gif_every == 0 and started:
            from drone.viz import compose, render_map

            st = patrol.drone_state(flight.telemetry(), False)
            path.append((st["x"], st["y"]))
            for v in patrol.verdicts:
                findings[v.bay_id] = v.issue
            src = camera or flight
            fr = src.latest_frame()
            ld = patrol.last_decision or {}
            cap = f"{ld.get('bay', '')}: {ld.get('issue', '')} {ld.get('severity', '')} -> {ld.get('next_action', '')}"
            frames.append(compose(render_map(site, path, st, findings), None if fr is None else fr.image, cap)[:, :, ::-1])
        if a.once and started and patrol.state == "IDLE":
            end_reason = "mission_landed"
            break
        if a.mode == "live" and link.snapshot().stop_requested:
            end_reason = "api_stop"
            break
        if a.mode == "live" and started and previous_state != "IDLE" and patrol.state == "IDLE":
            end_reason = "mission_landed"
            break
        if a.max_s and now - t0 > a.max_s:
            end_reason = "max_seconds"
            break
        time.sleep(max(0.0, period - (time.monotonic() - now)))
    if stop["reason"]:
        end_reason = stop["reason"]

    with open(a.log, "w") as f:
        f.writelines(json.dumps(asdict(e)) + "\n" for e in patrol.log)
    record_stats = recorder.close() if recorder else None
    if record_stats:
        log.info("recording %s", json.dumps(record_stats))
    final_state = patrol.drone_state(flight.telemetry(), link.snapshot().stop_requested)
    link.close()
    patrol.worker.close()
    if camera:
        camera.close()
    flight.close()
    duration_s = max(time.monotonic() - t0, 0.001)
    summary = {"ticks": tick, "hz": hz, "loop_hz": round(tick / duration_s, 2),
               "duration_s": round(duration_s, 1), "end_reason": end_reason,
               "verdicts": [{"bay": v.bay_id, "issue": v.issue, "severity": v.severity, "next": v.next_action}
                            for v in patrol.verdicts],
               "events_sent": sum(1 for s in link.sent if s["path"] == "/api/events"),
               "tasks_sent": [s["body"]["kind"] + "@" + s["body"]["zone_id"] for s in link.sent if s["path"] == "/api/tasks"],
               "commands": len(flight.commands), "recording": record_stats}
    log.info("summary %s", json.dumps(summary))
    if record_dir and a.build_twin_on_land is not None:
        _launch_twin_build(record_dir, a.build_twin_on_land, a.api, final_state)
    if a.gif and frames:
        import cv2
        import imageio.v2 as imageio

        Path(a.gif).parent.mkdir(parents=True, exist_ok=True)
        imageio.mimsave(a.gif, [cv2.resize(f, (f.shape[1] * 2 // 3, f.shape[0] * 2 // 3), interpolation=cv2.INTER_AREA) for f in frames], duration=0.25, loop=0)
        log.info("wrote %s (%d frames)", a.gif, len(frames))
    return 0


def _launch_twin_build(
    record_dir: Path, survey: str | None, api: str, state: dict[str, object]
) -> None:
    log_path = record_dir / "twin_build.log"
    command = [
        sys.executable,
        "-m",
        "drone.twin_build",
        "--recording",
        str(record_dir),
        "--api",
        api,
        "--state-json",
        json.dumps(state),
    ]
    if survey:
        command.extend(["--survey", str(Path(survey).expanduser().resolve())])
    try:
        with log_path.open("a", buffering=1) as log_file:
            subprocess.Popen(
                command,
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        log.info("started background twin build; log=%s", log_path)
    except OSError:
        log.exception("could not launch background twin build")


if __name__ == "__main__":
    raise SystemExit(main())
