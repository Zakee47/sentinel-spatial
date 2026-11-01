#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FOOTAGE_DIR="${SCRIPT_DIR}/footage"
mkdir -p "${FOOTAGE_DIR}"

curl -fL --retry 2 --connect-timeout 20 \
  "https://videos.pexels.com/video-files/5104001/5104001-hd_1920_1080_30fps.mp4" \
  -o "${FOOTAGE_DIR}/aisle.mp4"

curl -fL --retry 2 --connect-timeout 20 \
  "https://videos.pexels.com/video-files/5103996/5103996-hd_1920_1080_30fps.mp4" \
  -o "${FOOTAGE_DIR}/alt1.mp4"

curl -fL --retry 2 --connect-timeout 20 \
  "https://videos.pexels.com/video-files/10901926/10901926-hd_1920_1080_30fps.mp4" \
  -o "${FOOTAGE_DIR}/alt2.mp4"
