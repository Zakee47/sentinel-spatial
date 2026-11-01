from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

log = logging.getLogger("drone.twin_build")
ROOT = Path(__file__).resolve().parents[1]
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _post_status(api: str, state: dict[str, Any], status: str) -> None:
    if api == "none":
        return
    body = json.dumps({**state, "twin_build": status}).encode()
    request = urllib.request.Request(
        f"{api.rstrip('/')}/api/drone/state",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=2):
            pass
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.warning("could not publish twin_build=%s to API: %s", status, exc)


def build(recording: Path, survey: str | None, api: str, state: dict[str, Any]) -> int:
    recording = recording.expanduser().resolve()
    frames = recording / "frames"
    if not frames.is_dir() or not any(
        path.suffix.lower() in IMAGE_SUFFIXES for path in frames.iterdir()
    ):
        log.error("no recorded frames found under %s", frames)
        _post_status(api, state, "failed")
        return 1

    _post_status(api, state, "running")
    command = ["bash", str(ROOT / "scripts/drone_twin.sh"), str(frames)]
    if survey:
        command.append(str(Path(survey).expanduser().resolve()))
    env = os.environ.copy()
    env["PYTHON"] = sys.executable
    result = subprocess.run(command, cwd=ROOT, env=env, check=False)
    status = "done" if result.returncode == 0 else "failed"
    _post_status(api, state, status)
    log.info("twin build exited with status=%d (%s)", result.returncode, status)
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a twin from recorded live frames.")
    parser.add_argument("--recording", type=Path, required=True)
    parser.add_argument("--survey")
    parser.add_argument("--api", default="none")
    parser.add_argument("--state-json", default="{}")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    return build(args.recording, args.survey, args.api, json.loads(args.state_json))


if __name__ == "__main__":
    raise SystemExit(main())
