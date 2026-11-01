#!/usr/bin/env bash
set -uo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
missing=()
os=$(uname -s)

note_missing() {
  missing+=("$1")
  printf 'MISSING: %s\n' "$1"
}

case "$os" in
  Darwin)
    if command -v brew >/dev/null 2>&1; then
      brew install android-platform-tools scrcpy ffmpeg colmap coreutils python@3.11 node \
        || note_missing "Homebrew packages (rerun the failed brew install above)"
    else
      note_missing "Homebrew; install it from https://brew.sh, then rerun this script"
    fi
    ;;
  Linux)
    if command -v apt-get >/dev/null 2>&1; then
      if sudo apt-get update; then
        sudo apt-get install -y adb scrcpy ffmpeg colmap coreutils python3-venv \
          build-essential v4l2loopback-dkms libgl1 nodejs npm \
          || note_missing "one or more apt packages (rerun the failed apt install above)"
      else
        note_missing "apt package index (sudo apt-get update failed)"
      fi
    else
      note_missing "apt-get; install adb, scrcpy, ffmpeg, COLMAP, and Python 3.11+ manually"
    fi
    ;;
  *)
    note_missing "unsupported OS: $os (use macOS or Linux)"
    ;;
esac

python3_cmd=$(command -v python3 || true)
if [[ "$os" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
  brew_python="$(brew --prefix python@3.11 2>/dev/null)/bin/python3.11"
  [[ -x "$brew_python" ]] && python3_cmd="$brew_python"
fi
if [[ -z "$python3_cmd" ]]; then
  note_missing "python3 3.11+"
else
  if ! "$python3_cmd" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
    note_missing "Python 3.11 or later (found $("$python3_cmd" --version 2>&1))"
  elif [[ ! -x "$root/.venv/bin/python" ]]; then
    "$python3_cmd" -m venv "$root/.venv" || note_missing "could not create $root/.venv"
  fi
fi

if [[ -x "$root/.venv/bin/python" ]]; then
  if [[ "$os" == "Linux" ]]; then
    "$root/.venv/bin/python" -m pip install --upgrade pip \
      && "$root/.venv/bin/python" -m pip install 'torch>=2.6,<3' 'torchvision>=0.21,<1' \
        --index-url https://download.pytorch.org/whl/cpu \
      || note_missing "CPU PyTorch dependencies in .venv"
  else
    "$root/.venv/bin/python" -m pip install --upgrade pip \
      && "$root/.venv/bin/python" -m pip install 'torch>=2.6,<3' 'torchvision>=0.21,<1' \
      || note_missing "PyTorch dependencies in .venv"
  fi
  "$root/.venv/bin/python" -m pip install \
    -r "$root/drone/requirements-live.txt" \
    -r "$root/depth/requirements.txt" \
    -r "$root/twin/requirements-reconstruction.txt" \
    || note_missing "Python requirements (drone/live, depth, twin)"
else
  note_missing "Python virtual environment at $root/.venv"
fi

for command_name in adb scrcpy ffmpeg colmap docker node npm; do
  command -v "$command_name" >/dev/null 2>&1 || note_missing "$command_name on PATH"
done
if command -v docker >/dev/null 2>&1; then
  docker compose version >/dev/null 2>&1 || note_missing "Docker Compose plugin"
fi

if ((${#missing[@]})); then
  printf '\nSetup is incomplete. Resolve the missing items above and rerun:\n'
  printf '  %s\n' "${missing[@]}"
  exit 1
fi

printf '\nSetup complete. Run drone/LIVE_TWIN.md for service startup and capture.\n'
