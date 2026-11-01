# rea/ — REA setup for the DJI Fly investigation (W7)

- `setup.sh` — idempotent: checks Node (22.23.4+/24.22.1+/26.12.1+) and JDK 17, installs the latest JADX into `~/tools/jadx`, installs REA's `jadx-headless-mcp` bridge (SHA-256 checked), registers the REA MCP server, and prints the `PATH`/`REA_JADX_MCP_JAR` exports and an MCP config snippet.
- `evidence.py` — turns REA/JADX outputs into bounded, names-only evidence files under `docs/rea/evidence/` (no code bodies).

Run: `./rea/setup.sh`, then follow the printed exports. Commands, provenance and findings: [`docs/rea/README.md`](../docs/rea/README.md), [`docs/rea/REPORT.md`](../docs/rea/REPORT.md), demo: [`docs/rea/DEMO.md`](../docs/rea/DEMO.md).

Scope: Zak's own drone, phone and DJI Fly install; interoperability analysis only; never modify firmware, never bypass DJI safety features, no decryption/auth circumvention, no DJI code committed. The APK stays outside the repo (`~/dji/`).
