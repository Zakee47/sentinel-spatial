# 60-second demo: "How does this app fly the drone?"

**Setup before going on stage** (one-off, ~3 min): `./rea/setup.sh`, then `export PATH="$HOME/tools/jadx/bin:$PATH" REA_JADX_MCP_JAR=$HOME/tools/jadx-headless-mcp-0.7.1-all.jar`. The official DJI Fly APK is at `~/dji/dji-fly-1.21.18.apk` (see [README.md](README.md) for the official download). Warm the cache once by running each command below. Have [REPORT.md](REPORT.md) open in a second tab.

| Time | Zak says | On screen |
| --- | --- | --- |
| 0:00 | "The Neo 2 has no SDK. So we asked Devin, using REA, to read our own copy of DJI's app and tell us how it flies the drone. Names only, no firmware, no safety bypass." | Devin session with the prompt below |
| 0:10 | "First, what is this app?" | `npx --yes rea-agents@latest inspect-android-package ~/dji/dji-fly-1.21.18.apk --format json` → package `dji.go.v5`, version 1.21.18, USB accessory + Wi-Fi |
| 0:20 | "Is there a public DJI SDK inside? No." | `npx --yes rea-agents@latest search-android-classes ~/dji/dji-fly-1.21.18.apk dji.sdk --format json` → 0 matches |
| 0:30 | "Two links: Wi-Fi straight to the drone, or USB to the RC-N3, then OcuSync." | `grep -E "Aoa|WifiControl" docs/rea/evidence/components.txt` |
| 0:38 | "Flight commands are a private virtual-stick key; video comes back through native decoders and leaves through a built-in RTMP streamer." | `grep -E "VirtualStick|livestream|OcuSync|NEO2" docs/rea/evidence/native-architecture-strings.txt`; `grep -E "ilink|rtmp|liveshare|_proto" docs/rea/evidence/arm64-libs-*.txt` |
| 0:48 | "Verdict: we won't hack the control link. We use DJI's official RTMP stream for live video, our simulator for autonomy, and a Mini 4 Pro on MSDK for the real thing." | Mermaid diagram + verdict table in REPORT.md; dashboard REA panel reading `docs/rea/findings.json` |
| 0:58 | "That's a two-week RE question answered in a minute." | — |

**Devin prompt (live, MCP):**

> Using the REA MCP tools on `/home/ubuntu/dji/dji-fly-1.21.18.apk` (our own DJI Fly install, interoperability only, names only — no decompiled code, no decryption): how does this app fly the drone? Inspect the package, search classes for `dji.sdk`, `WiFi` and `livestream`, and tell me the control link, the video path and whether there's an official way to get video out. One paragraph plus a list of evidence names.

REA MCP tools behind that prompt (same as the CLI commands): `inspect-android-package`, `search-android-classes`. Register the MCP server with `npx rea-agents setup` (the script does this non-interactively for Devin) and restart the agent.

**Fallback if Wi-Fi / npm is slow on stage:** show the saved outputs in [`evidence/`](evidence/) and REPORT.md; the story is identical.
