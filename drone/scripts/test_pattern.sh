#!/usr/bin/env bash
set -euo pipefail

command -v ffmpeg >/dev/null || {
  echo "ffmpeg is required (install it to publish the test pattern)" >&2
  exit 1
}
echo "Publishing a test pattern to rtmp://localhost:1935/live/neo (Ctrl-C to stop)."
exec ffmpeg -hide_banner -loglevel warning -re \
  -f lavfi -i "testsrc=size=640x360:rate=10" \
  -an -c:v libx264 -preset ultrafast -tune zerolatency -g 10 -keyint_min 10 \
  -pix_fmt yuv420p -f flv rtmp://localhost:1935/live/neo
