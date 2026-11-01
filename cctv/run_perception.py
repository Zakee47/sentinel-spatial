"""Run perception against a CCTV camera without touching perception/.

python -m cctv.run_perception --camera camera-1 [--source rtsp://...] [-- extra perception.run args]

Resolves the URI from cameras.local.yaml/cameras.example.yaml (with ${VAR} credential
expansion), forces FFmpeg TCP transport + low-latency options, then execs perception.run.
`perception.run` already accepts any OpenCV source string, including rtsp:// URLs.
"""

from __future__ import annotations

import argparse
import os
import sys

from cctv.sources import FFMPEG_OPTS, expand_env, load_cameras, redact


def build_argv(camera: str, source: str, extra: list[str]) -> list[str]:
    return [sys.executable, "-m", "perception.run", "--source", source, "--camera", camera, *extra]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", default="camera-1")
    ap.add_argument("--source", default=None)
    ap.add_argument("--config", default=None)
    a, extra = ap.parse_known_args()
    extra = [x for x in extra if x != "--"]
    uri = a.source or load_cameras(a.config).get(a.camera)
    if not uri:
        raise SystemExit(f"no URI for {a.camera}; pass --source or add it to cctv/cameras.local.yaml")
    uri = expand_env(uri)
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", FFMPEG_OPTS)
    print(f"[cctv] {a.camera} <- {redact(uri)}", flush=True)
    argv = build_argv(a.camera, uri, extra)
    os.execv(argv[0], argv)


if __name__ == "__main__":
    main()
