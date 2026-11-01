#!/usr/bin/env bash
set -euo pipefail

node -e 'const [a,b,c]=process.versions.node.split(".").map(Number); if (!((a===22 && (b>23 || b===23 && c>=4)) || (a===24 && (b>22 || b===22 && c>=1)) || (a===26 && (b>12 || b===12 && c>=1)) || a>26)) { console.error("Unsupported Node version: " + process.versions.node); process.exit(1); }'
java_version=$(java -version 2>&1 | head -1)
[[ "$java_version" =~ version\ \"17[.\"] ]] || { echo "JDK 17 required: $java_version" >&2; exit 1; }
javac_version=$(javac -version 2>&1)
[[ "$javac_version" =~ ^javac\ 17([.]|$) ]] || { echo "JDK 17 compiler required: $javac_version" >&2; exit 1; }
command -v ps >/dev/null

release=$(curl -fsSL -o /dev/null -w '%{url_effective}' https://github.com/skylot/jadx/releases/latest)
tag=${release##*/}
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Unexpected JADX release: $release" >&2; exit 1; }
version=${tag#v}
dest="$HOME/tools/jadx"
mkdir -p "$HOME/tools"
if [[ ! -x "$dest/bin/jadx" ]] || [[ "$("$dest/bin/jadx" --version)" != "$version" ]]; then
  staging=$(mktemp -d "$HOME/tools/.jadx.XXXXXXXX")
  trap 'rm -rf "$staging"' EXIT
  curl -fsSL "https://github.com/skylot/jadx/releases/download/$tag/jadx-$version.zip" -o "$staging/jadx.zip"
  mkdir "$staging/extracted"
  unzip -q "$staging/jadx.zip" -d "$staging/extracted"
  chmod +x "$staging/extracted/bin/jadx" "$staging/extracted/bin/jadx-gui"
  if [[ -e "$dest" ]]; then
    echo "Existing JADX installation at $dest differs from $version; move it aside before upgrading." >&2
    exit 1
  fi
  mv "$staging/extracted" "$dest"
fi
export PATH="$dest/bin:$PATH"
echo "JADX $(jadx --version) installed at $dest"

bridge="$HOME/tools/jadx-headless-mcp-0.7.1-all.jar"
bridge_hash=6e5eacf500b64292bfb73c49797c1958f6ee44646e43e868039ae7feb573ff75
if [[ ! -f "$bridge" ]]; then
  download=$(mktemp "$HOME/tools/.jadx-bridge.XXXXXXXX")
  trap 'rm -f "$download"; [[ -z "${staging:-}" ]] || rm -rf "$staging"' EXIT
  curl -fsSL https://github.com/1013503897/jadx-headless-mcp/releases/download/v0.7.1/jadx-headless-mcp-0.7.1-all.jar -o "$download"
  echo "$bridge_hash  $download" | sha256sum -c -
  mv "$download" "$bridge"
fi
echo "$bridge_hash  $bridge" | sha256sum -c -
export REA_JADX_MCP_JAR="$bridge"

# Acquire from a trusted directory, not the analyzed project.
cd "$HOME"
npx --yes rea-agents@latest setup --client devin --yes
printf '\nAdd JADX to your shell PATH: export PATH="%s/bin:$PATH"\n' "$dest"
printf 'Set in your shell: export REA_JADX_MCP_JAR="%s"\n' "$bridge"
printf 'Manual MCP config: {"mcpServers":{"rea":{"command":"npx","args":["-y","rea-agents@latest","mcp"],"env":{"REA_JADX_MCP_JAR":"%s"}}}}\n' "$bridge"
