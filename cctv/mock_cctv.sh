#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname -- "$SCRIPT_DIR")"
DEFAULT_FOOTAGE="$SCRIPT_DIR/footage/cctv_retail.mp4"
if [[ ! -f "$DEFAULT_FOOTAGE" ]]; then
  DEFAULT_FOOTAGE="$REPO_ROOT/perception/footage/aisle.mp4"
  [[ -f "$DEFAULT_FOOTAGE" ]] || DEFAULT_FOOTAGE="$REPO_ROOT/../perception/footage/aisle.mp4"
fi
FOOTAGE="${1:-${CCTV_FOOTAGE:-$DEFAULT_FOOTAGE}}"
[[ "$FOOTAGE" = /* ]] || FOOTAGE="$REPO_ROOT/$FOOTAGE"
CAMERA_ID="${CAMERA_ID:-camera-1}"
CCTV_FPS="${CCTV_FPS:-30}"
VERSION="v1.9.3"
BIN_DIR="$SCRIPT_DIR/bin"
RTSP_URL="rtsp://localhost:8554/$CAMERA_ID"
MEDIA_PID=""
FFMPEG_PID=""

cleanup() {
  trap - EXIT INT TERM
  [[ -z "$FFMPEG_PID" ]] || kill "$FFMPEG_PID" 2>/dev/null || true
  [[ -z "$MEDIA_PID" ]] || kill "$MEDIA_PID" 2>/dev/null || true
  [[ -z "$FFMPEG_PID" ]] || wait "$FFMPEG_PID" 2>/dev/null || true
  [[ -z "$MEDIA_PID" ]] || wait "$MEDIA_PID" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ ! -f "$FOOTAGE" ]]; then
  printf 'Footage not found: %s\nUsage: %s [footage.mp4] (or set CCTV_FOOTAGE)\n' "$FOOTAGE" "$0" >&2
  exit 1
fi
if [[ ! "$CAMERA_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo 'CAMERA_ID must contain only letters, digits, underscores, or hyphens.' >&2
  exit 1
fi
if [[ ! "$CCTV_FPS" =~ ^[1-9][0-9]*$ ]]; then
  echo 'CCTV_FPS must be a positive integer.' >&2
  exit 1
fi
for cmd in curl tar ffmpeg; do
  command -v "$cmd" >/dev/null || { echo "Required command missing: $cmd" >&2; exit 1; }
done

mkdir -p "$BIN_DIR"
if [[ ! -x "$BIN_DIR/mediamtx" ]]; then
  curl -fL --retry 2 --connect-timeout 20 \
    "https://github.com/bluenviron/mediamtx/releases/download/$VERSION/mediamtx_${VERSION}_linux_amd64.tar.gz" \
    -o "$BIN_DIR/mediamtx.tar.gz"
  tar -xzf "$BIN_DIR/mediamtx.tar.gz" -C "$BIN_DIR" mediamtx
  rm "$BIN_DIR/mediamtx.tar.gz"
fi

cat > "$BIN_DIR/mediamtx.yml" <<'YAML'
logLevel: info
rtspAddress: :8554
protocols: [tcp]
rtmp: no
hls: no
webrtc: no
srt: no
paths:
  all_others:
YAML
"$BIN_DIR/mediamtx" "$BIN_DIR/mediamtx.yml" &
MEDIA_PID=$!

ready=false
for ((i = 0; i < 50; i++)); do
  kill -0 "$MEDIA_PID" 2>/dev/null || { echo 'MediaMTX exited during startup.' >&2; exit 1; }
  if (echo > /dev/tcp/127.0.0.1/8554) 2>/dev/null; then
    ready=true
    break
  fi
  sleep 0.1
done
[[ "$ready" = true ]] || { echo 'MediaMTX did not open port 8554.' >&2; exit 1; }

FONT="font=monospace"
if [[ -f /usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf ]]; then
  FONT="fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
fi
FILTER="scale=1280:720,drawtext=$FONT:text='CAM-01  AISLE 3':x=20:y=20:fontsize=28:fontcolor=white:box=1:boxcolor=black@0.75:boxborderw=8"
FILTER+=",drawtext=$FONT:text='%{localtime}':x=20:y=60:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.75:boxborderw=8"
FILTER+=",drawtext=$FONT:text='REC':x=w-tw-24:y=20:fontsize=24:fontcolor=red:box=1:boxcolor=black@0.75:boxborderw=8"
printf 'Publishing %s -> %s\n' "$FOOTAGE" "$RTSP_URL"
ffmpeg -hide_banner -loglevel warning -nostdin -re -stream_loop -1 -i "$FOOTAGE" \
  -an -vf "$FILTER" -r "$CCTV_FPS" -c:v libx264 -preset veryfast -tune zerolatency \
  -pix_fmt yuv420p -g "$CCTV_FPS" -keyint_min "$CCTV_FPS" -sc_threshold 0 \
  -f rtsp -rtsp_transport tcp "$RTSP_URL" &
FFMPEG_PID=$!
wait -n "$MEDIA_PID" "$FFMPEG_PID"
