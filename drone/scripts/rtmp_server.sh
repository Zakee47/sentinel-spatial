#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$SCRIPT_DIR/.bin"
MEDIAMTX="$BIN_DIR/mediamtx"
CONFIG="$SCRIPT_DIR/mediamtx.yml"

if [[ ! -x "$MEDIAMTX" ]]; then
  command -v curl >/dev/null || { echo "curl is required to download MediaMTX" >&2; exit 1; }
  command -v tar >/dev/null || { echo "tar is required to unpack MediaMTX" >&2; exit 1; }
  command -v python3 >/dev/null || { echo "python3 is required to resolve the latest release" >&2; exit 1; }

  case "$(uname -s)" in
    Linux) os=linux ;;
    Darwin) os=darwin ;;
    *) echo "Unsupported operating system: $(uname -s)" >&2; exit 1 ;;
  esac
  case "$(uname -m)" in
    x86_64|amd64) arch=amd64 ;;
    aarch64|arm64) arch=arm64 ;;
    *) echo "Unsupported architecture: $(uname -m) (need amd64 or arm64)" >&2; exit 1 ;;
  esac

  tag="$(curl -fsSL https://api.github.com/repos/bluenviron/mediamtx/releases/latest \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["tag_name"])')"
  mkdir -p "$BIN_DIR"
  archive="mediamtx_${tag}_${os}_${arch}.tar.gz"
  url="https://github.com/bluenviron/mediamtx/releases/download/${tag}/${archive}"
  echo "Downloading MediaMTX ${tag} (${os}/${arch})..."
  curl -fsSL "$url" | tar -xz -C "$BIN_DIR" mediamtx
  chmod +x "$MEDIAMTX"
fi

case "$(uname -s)" in
  Linux)
    lan_ip="$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')"
    if [[ -z "$lan_ip" ]]; then
      lan_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    fi
    ;;
  Darwin)
    lan_ip="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
    ;;
esac
lan_ip="${lan_ip:-<laptop-ip>}"

echo "Laptop LAN IP: $lan_ip"
echo "Enter this RTMP URL in DJI Fly if its RTMP publisher is available:"
echo "  rtmp://${lan_ip}:1935/live/neo"
echo "MediaMTX listening on TCP port 1935 (Ctrl-C to stop)."
exec "$MEDIAMTX" "$CONFIG"
