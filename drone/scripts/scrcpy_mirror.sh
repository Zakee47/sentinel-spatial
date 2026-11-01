#!/usr/bin/env bash
set -euo pipefail

crop=""
video_device="${SENTINEL_VIDEO_DEVICE:-/dev/video10}"
while (($#)); do
  case "$1" in
    --crop)
      [[ $# -ge 2 ]] || { echo "--crop requires W:H:X:Y" >&2; exit 2; }
      crop="$2"
      shift 2
      ;;
    --device)
      [[ $# -ge 2 ]] || { echo "--device requires a device path" >&2; exit 2; }
      video_device="$2"
      shift 2
      ;;
    *)
      echo "Usage: $0 [--crop W:H:X:Y] [--device /dev/videoN]" >&2
      exit 2
      ;;
  esac
done

command -v scrcpy >/dev/null || {
  echo "scrcpy is required; see drone/LIVE_FEED.md for installation steps" >&2
  exit 1
}
command -v adb >/dev/null || {
  echo "adb is required; install Android platform tools and see drone/LIVE_FEED.md" >&2
  exit 1
}

os="$(uname -s)"
if [[ "$os" == "Linux" && -e "$video_device" ]]; then
  echo "Mirroring to $video_device; use --source ${video_device##*/video} in Sentinel."
  args=(
    --v4l2-sink="$video_device"
    --no-playback
    --max-fps=30
    --video-bit-rate=8M
    --stay-awake
    --window-title=SentinelNeo
    --no-audio
    --no-control
  )
else
  echo "Mirroring in a window. Capture it with --source screen:L,T,W,H."
  args=(
    --max-fps=30
    --video-bit-rate=8M
    --stay-awake
    --window-title=SentinelNeo
    --no-audio
    --no-control
  )
fi
if [[ -n "$crop" ]]; then
  args+=(--crop="$crop")
fi
adb devices
exec scrcpy "${args[@]}"
