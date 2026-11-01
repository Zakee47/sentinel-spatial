#!/usr/bin/env bash
set -euo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
if command -v cloudflared >/dev/null 2>&1; then
  cloudflared_bin="$(command -v cloudflared)"
else
  cloudflared_bin="$dir/.bin/cloudflared"
  if [[ ! -x "$cloudflared_bin" ]]; then
    mkdir -p "$dir/.bin"
    case "$(uname -m)" in
      x86_64) arch=amd64 ;;
      aarch64|arm64) arch=arm64 ;;
      *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
    esac
    curl -fL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$arch" -o "$cloudflared_bin"
    chmod +x "$cloudflared_bin"
  fi
fi
"$cloudflared_bin" tunnel --url "http://localhost:${PORT:-8000}" 2>&1 | awk '
  { print > "/dev/stderr"; if (match($0, /https:\/\/[a-zA-Z0-9-]+\.trycloudflare\.com/)) { print substr($0, RSTART, RLENGTH); fflush() } }
'
