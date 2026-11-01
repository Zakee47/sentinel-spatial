# Sentinel — hackathon build plan (OpenAI hackathon, 1.5 h build)

Full product brief: [BRIEF.md](BRIEF.md). Contracts every workstream must follow: [../contracts/API.md](../contracts/API.md), [../db/schema.sql](../db/schema.sql), [../config/site.yaml](../config/site.yaml).

## Decisions (from Zak)
- **Hybrid**: real perception on one stock-footage clip (mocked "fixed CCTV" camera-1) + a simulated-floor fallback that emits the same events.
- **Two cameras**: camera-1 = stock footage (mocked), drone-1 = **live** DJI Neo 2 video from the empty warehouse Zak is in.
- **Drone is the wow factor**: live feed → Decisions API bay checks on the 3D map; SimDriver patrol with code safety supervisor; **REA** analysis of the DJI Fly app's control/video path; **Devin API as the mission manager** (plans patrols, raises tasks; never in the flight loop).
- **Twin**: real COLMAP if feasible (from footage / drone video), else boxes or NVIDIA SimReady GLB assets (`codepawl/simready-glb`).
- OpenAI: **Decisions API** (`gpt-6-luna`) for every judgement call. Devin API for agentic work.
- Stack: Python 3.11 + FastAPI + PostgreSQL (docker-compose) + three.js/Vite dashboard. Laptop-run; hosted **read-only** dashboard replays recorded events (GitHub Pages).
- Look: Devin design system, with a layout that feels like Cactus (getcactus.ai): big 3D twin, shelf-attention heatmap, side panels, "Ask" box.
- Mocked: product catalogue + till sales. Out: CRM, staff phone notifications, shift-summary delivery. No face blur needed (no faces stored anyway).
- Thresholds: brief defaults.

## Workstreams (one Devin each, one folder each, one PR each)
| # | Folder | Owner output |
| --- | --- | --- |
| W1 | `server/`, `docker-compose.yml`, `replay/` | FastAPI + Postgres, all REST/WS in contracts, seed products/sales, simulated floor + simulated drone fallback, replay recorder, `/api/ask`, `/api/summary`, mission queue, `/api/agent/*` |
| W2 | `decisions/` | Real Decisions API implementation of the fixed signatures, question sets JSON, threshold policy, decisions_log, tests, label/threshold sweep script |
| W3 | `perception/` | Stock footage, YOLO26-pose tracking, ankle→floor projection, head direction, gaze cone vs zones, look/interest/pick_up/put_back/kept events → `POST /api/events` |
| W4 | `twin/` | COLMAP pipeline → metric, twin-frame point cloud assets in `twin/out/`; fallback boxes/SimReady scene |
| W5 | `dashboard/` | three.js + Vite dashboard (Cactus-like, Devin design system), live WS + replay mode, GitHub Pages deploy |
| W6 | `drone/` | `DroneDriver` interface, `SimDriver`, `LiveFeedDriver` (Neo 2 video via phone mirror/RTMP/capture), safety supervisor, patrol state machine, bay inspection via decisions, state push |
| W7 | `rea/`, `docs/rea/` | REA analysis of the DJI Fly Android app: control + video path, live-stream options for Neo 2, findings report + demo script |
| W8 | `agent/` | `sentinel_agent.launch()` — Devin API mission manager + its prompt, tunnel instructions, mock mode |

Rules for every workstream: only edit your own folder (plus your own README section); never change `contracts/`, `db/schema.sql`, `config/site.yaml` (if a contract change is essential, say so in the PR description instead); `ruff` + `pytest` for Python; secrets only from env (`OPENAI_API_KEY`, `DEVIN_API_KEY`), never committed; respect the brief's drone guardrails (no firmware changes, never bypass DJI safety, no AI/network calls in the flight loop).

## Demo script (target)
1. Open the dashboard on the 3D twin: retail set + 4 rack bays, camera-1 and drone placed.
2. Stock-footage shopper plays: heatmap builds on shelf zones, funnel ticks, a `put_back` appears with confidence.
3. Funnel flags a "high attention, low conversion" product.
4. "Ask Sentinel": "which shelf underperformed?" → answer from the event store.
5. Devin mission agent is launched → plans a patrol → drone (live Neo 2 feed + sim position) checks bays → Decisions API flags the empty pick face and misplaced carton → restock/move tasks appear.
6. REA slide/panel: how DJI Fly drives the Neo 2, and our safe integration path.
7. Close on privacy: edge-only video, only crops to the API, no identities.

## Timeline (GMT)
- 16:30 workstreams start · **17:00 PRs open** (whatever works, mergeable) · 17:00–17:25 integration + end-to-end run · 17:25–17:40 demo recording.
