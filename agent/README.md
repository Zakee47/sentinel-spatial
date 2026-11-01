# Sentinel Devin mission agent

Creates a minutes-scale planning session, not a flight controller. The local
drone supervisor always validates missions. The planner never bypasses drone
safety, sends flight commands, modifies firmware, sensing, geofence or RTH, or
calls stop unless explicitly requested. Respect mission rejection; do not spam
retries. Exposing a local API via a public quick tunnel makes it reachable by
others: use only a non-sensitive demo API and stop the tunnel afterward.

From the repository root (Python 3.11+):

```sh
python -m venv agent/.venv
source agent/.venv/bin/activate
pip install -e 'agent[dev]'
uvicorn agent.stub_server:app --port 8000
# in another shell, with the same venv activated:
python -m agent.cli 'end-of-shift stock check' --api-base http://localhost:8000 --wait
python -m agent.cli --list
python -m agent.cli --status SESSION_ID
```

Mock mode makes HTTP calls to the provided API in a background thread and
stores completed/failed status; use `--wait` for CLI mock runs so the thread
finishes before process exit. The stub is in-memory and resets on restart; it
is for local testing, not flight safety validation. Python callers can use
`from sentinel_agent import launch, list_runs, status, simulate_mission` after
the editable install. `simulate_mission` is synchronous and accepts an optional
httpx-compatible client for tests.

For real Devin sessions, start the Sentinel API, run `bash agent/tunnel.sh`
(downloads cloudflared into ignored `agent/.bin` if absent), and pass the
printed HTTPS URL as `--api-base`. Set `DEVIN_API_KEY` in the environment,
never in a file or prompt. Mock mode is the default; set `SENTINEL_AGENT_MOCK=0` for real launches. `cog_` keys select v3 org-scoped session creation (`DEVIN_ORG_ID`, default `org-3e3903fc352442af8b96c7a5098f0774`);
other keys select legacy v1. `DEVIN_API_VERSION=v1|v3` overrides selection;
`DEVIN_API_BASE` overrides `https://api.devin.ai`. Real status queries call
the Devin API; `--wait` is mock-only. `SENTINEL_AGENT_RUNS` overrides the
default `agent/.runs.json` run store. `PORT` controls the tunnel's local port.
Run `cd agent && ruff check . && pytest -q` to test.
