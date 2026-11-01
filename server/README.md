# Sentinel server (W1)

FastAPI + PostgreSQL backend implementing every REST and WebSocket endpoint in
[`contracts/API.md`](../contracts/API.md). Applies [`db/schema.sql`](../db/schema.sql) at startup,
loads [`config/site.yaml`](../config/site.yaml) with pydantic, seeds a mocked 20-SKU UK grocery
catalogue and hourly till sales for today.

## Run

```bash
docker compose up --build            # postgres:16 + app on http://localhost:8000
pip install httpx pyyaml pydantic    # (or: pip install -r server/requirements.txt)
python -m server.sim                 # simulated floor + drone -> live WS stream
```

Without Docker for the app (only Postgres in Docker):

```bash
docker compose up -d db
pip install -r server/requirements.txt && pip install -e decisions
SENTINEL_DECISIONS_MOCK=1 uvicorn server.app:app --reload --port 8000
```

Env: `DATABASE_URL` (default `postgresql://sentinel:sentinel@localhost:5432/sentinel`),
`SENTINEL_DECISIONS_MOCK=1` (no OpenAI calls; docker-compose defaults to 1, set `SENTINEL_DECISIONS_MOCK=0`
to use the real Decisions API for "Ask"), `SENTINEL_RECORD=replay/demo.jsonl` (record every WS message),
`SENTINEL_PUBLIC_API` (public tunnel URL handed to the Devin mission agent), `OPENAI_API_KEY`, `DEVIN_API_KEY`.

## Simulator (`python -m server.sim`)

- **Floor**: shoppers walk the aisle floor (y 1.0–1.8 m) past the 4 shelf sections and emit `pass_by`,
  `look` (`duration_s`, `gaze_hit_xyz` on the shelf face), `interest` (≥ 5 s), `pick_up`
  (`holding_product` decision) and `put_back`/`kept` (`reach_outcome` decision), with confidences and
  policies from `site.yaml` thresholds (some land in `review`). **SKU-007 (Lindt Excellence 70%)** is the
  planted *high attention, low conversion* product: most looks, mostly put back, barely sells.
- **Drone**: pure-software patrol posting `DroneState` at 2 Hz (IDLE → TAKEOFF → GOTO_BAY → INSPECT →
  DECIDE → RETURN → LAND), inspecting each bay from `y = 8.0 − standoff` at 1.5 m, ≤ 0.8 m/s, inside the
  geofence. `bay-B-02` → `bay_issue: empty / act_now` (+ `restock` task), `bay-B-03` →
  `misplaced / act_today` (+ `move` task). It flies queued missions from `GET /api/drone/mission`, otherwise
  auto-patrols all 4 bays, and lands immediately when `stop_requested` is set.
- Flags: `--duration 180`, `--no-drone` (when `drone/` pushes real state), `--no-floor`, `--shopper-gap 2.5`, `--api`.

## Replay

`SENTINEL_RECORD=replay/demo.jsonl` writes `{"t": seconds_since_start, "msg": <ws message>}` per line.
The committed `replay/demo.jsonl` is ~3 minutes of the simulator (fresh DB, one agent mission for bays
B-02/B-03). `replay/site.json` / `replay/products.json` are static copies for the hosted dashboard.
Regenerate:

```bash
SENTINEL_RECORD=replay/demo.jsonl uvicorn server.app:app --port 8000 &
python -m server.sim --duration 185 --shopper-gap 2.0
python -c "import json; from server.config import raw_site; from server.seed import products; \
json.dump(raw_site(), open('replay/site.json','w'), indent=2); json.dump(products(), open('replay/products.json','w'), indent=2)"
```

## Implementation notes

- `GET /api/heatmap` / `/api/funnel` default `since` = start of today (UTC). Funnel: an event counts for a
  product if it names it, or names no product but is in the product's zone (e.g. `pass_by`). `sold` joins
  `sales`. Flag = `looked > 0` and looked in the top quartile and `kept + sold` in the bottom quartile.
- Heatmap is also pushed on WS as `{"kind": "heatmap"}` at most 2 Hz after look/interest events.
- `/api/review/{id}` stores the verdict in `payload.review` (schema unchanged); reviewed events leave `/api/review`.
- `/api/ask`: intent from `sentinel_decisions.ask_intent()` over 7 fixed intents; in mock mode (whose mock
  always returns the first intent) or on `unclear`/timeout it falls back to a keyword router. Answers are
  templated sentences over SQL results.
- Drone state/missions are in memory. `POST /api/drone/stop` sets a sticky `stop_requested` (overrides
  whatever `drone/` posts) and cancels missions; a new accepted mission clears it. Missions are rejected for
  unknown bays, low battery (< `min_battery_pct`) or when one is already pending/active. A mission becomes
  `active` when `drone/` posts its `mission_id`, `done` when it then posts `IDLE`. The server never sends
  flight commands — `drone/`'s safety supervisor owns validation and execution.
- `/api/agent/run` imports `sentinel_agent` from `agent/`; if it isn't there yet → `503` with a clear message.

## curl examples

```bash
curl localhost:8000/api/health
curl localhost:8000/api/products
curl -X POST localhost:8000/api/events -H 'content-type: application/json' \
  -d '{"zone_id":"aisle-A-shelf-2","type":"look","product_id":"SKU-007","x":2.1,"y":1.4,"z":0,"source":"camera-1","confidence":0.91,"payload":{"duration_s":2.3,"gaze_hit_xyz":[2.1,2.0,1.1]}}'
curl 'localhost:8000/api/events?type=look&limit=5'
curl localhost:8000/api/heatmap
curl localhost:8000/api/funnel
curl -X POST localhost:8000/api/tasks -H 'content-type: application/json' -d '{"zone_id":"bay-B-02","kind":"restock","severity":3,"note":"empty pick face"}'
curl 'localhost:8000/api/tasks?status=open'
curl -X PATCH localhost:8000/api/tasks/<task_id> -H 'content-type: application/json' -d '{"status":"done","assignee":"sam"}'
curl localhost:8000/api/review
curl -X POST localhost:8000/api/review/<event_id> -H 'content-type: application/json' -d '{"verdict":"confirm"}'
curl localhost:8000/api/drone/state
curl -X POST localhost:8000/api/drone/mission -H 'content-type: application/json' -d '{"bays":["bay-B-02","bay-B-03"],"reason":"stock check","requested_by":"user"}'
curl localhost:8000/api/drone/mission
curl -X POST localhost:8000/api/drone/stop
curl -X POST localhost:8000/api/ask -H 'content-type: application/json' -d '{"question":"Which shelf underperformed?"}'
curl localhost:8000/api/summary
curl -X POST localhost:8000/api/agent/run -H 'content-type: application/json' -d '{"goal":"end-of-shift stock check"}'
curl localhost:8000/api/agent/runs
websocat ws://localhost:8000/ws      # or: python -c "import asyncio,websockets; ..."
```

## Tests

```bash
docker compose up -d db
python -m pytest server/tests -q     # logic tests always run; API tests skip if Postgres is unreachable
```
