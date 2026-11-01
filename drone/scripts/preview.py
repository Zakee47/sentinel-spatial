#!/usr/bin/env python3
"""Preview a live feed, or save one frame in headless mode."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import yaml


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="OpenCV index, URL, file, or screen region")
    parser.add_argument("--crop", help="crop in source pixels (x,y,w,h) or fractions (x,y,w,h)")
    parser.add_argument("--snapshot", help="save one frame here and exit without opening a window")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))
    from drone.live import LiveFeedDriver

    with (repo_root / "config" / "site.yaml").open(encoding="utf-8") as config_file:
        site = yaml.safe_load(config_file)
    driver = LiveFeedDriver(args.source, site, crop=args.crop)
    last_ts = 0.0
    fps_started = time.monotonic()
    fps_count = 0
    reported_fps = 0.0
    try:
        if args.snapshot:
            deadline = time.monotonic() + 15
            frame = None
            first_frame_ts = 0.0
            frame_count = 0
            started = time.monotonic()
            while time.monotonic() < deadline:
                candidate = driver.latest_frame()
                if candidate is not None and candidate.ts != last_ts:
                    last_ts = candidate.ts
                    if first_frame_ts == 0.0:
                        first_frame_ts = candidate.ts
                    frame_count += 1
                    frame = candidate
                if frame is not None and time.monotonic() - started >= 1:
                    break
                time.sleep(0.02)
            if frame is None:
                raise RuntimeError("no frame received within 15 seconds")
            snapshot = Path(args.snapshot)
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(snapshot), frame.image):
                raise RuntimeError(f"could not write snapshot: {snapshot}")
            telemetry = driver.telemetry()
            elapsed = frame.ts - first_frame_ts
            measured_fps = (frame_count - 1) / elapsed if elapsed > 0 else 0.0
            print(
                f"snapshot={snapshot} size={frame.image.shape[1]}x{frame.image.shape[0]} "
                f"fps={measured_fps:.1f} portal_fix={telemetry.has_fix}"
            )
            return

        while True:
            frame = driver.latest_frame()
            if frame is not None and frame.ts != last_ts:
                last_ts = frame.ts
                fps_count += 1
                cv2.imshow("Sentinel live feed", frame.image)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            now = time.monotonic()
            if now - fps_started >= 1:
                reported_fps = fps_count / (now - fps_started)
                fps_count = 0
                fps_started = now
                telemetry = driver.telemetry()
                print(
                    f"fps={reported_fps:.1f} portal_fix={telemetry.has_fix} "
                    f"position=({telemetry.x:.2f}, {telemetry.y:.2f}, {telemetry.z:.2f})"
                )
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        driver.close()
        if not args.snapshot:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
