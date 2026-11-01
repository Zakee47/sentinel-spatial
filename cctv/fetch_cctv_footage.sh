#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname -- "$SCRIPT_DIR")"
PYTHON="$REPO_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  python3 -m venv "$REPO_ROOT/.venv"
fi
if ! "$PYTHON" -m yt_dlp --version >/dev/null 2>&1; then
  "$PYTHON" -m pip install yt-dlp
fi
mkdir -p "$SCRIPT_DIR/footage"
"$PYTHON" -m yt_dlp \
  -f 'bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b' \
  --merge-output-format mp4 \
  -o "$SCRIPT_DIR/footage/cctv_retail.%(ext)s" \
  'https://www.youtube.com/watch?v=-1bRhYjw1qE'
