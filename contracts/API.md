# Sentinel contracts (all workstreams code against this file)

Server: FastAPI at `SENTINEL_API` (default `http://localhost:8000`). All coordinates are metres in the twin frame (`config/site.yaml`).

## Event (JSON) — mirrors `db/schema.sql` `events`
```json
{
  "event_id": "01J...ULID",        // optional on POST; server fills it
  "ts": "2026-11-01T16:20:00Z",    // optional on POST; server fills now()
  "site_id": "demo-warehouse",
  "zone_id": "aisle-A-shelf-2",
  "type": "look",                  // pass_by|look|interest|pick_up|put_back|kept|bay_issue|hazard|task|patrol
  "product_id": "SKU-007",         // nullable
  "x": 2.1, "y": 1.4, "z": 0.0,    // person floor position / drone position / bay centre
  "source": "camera-1",            // camera-1|drone-1|pos|agent|sim
  "track_id": "t17",               // nullable, short-lived
  "decision": {"question": "reach_outcome", "answer": {...}, "policy": "auto"},   // nullable
  "confidence": 0.91,              // nullable
  "crop_ref": "crops/abc.jpg",     // local path only, nullable
  "payload": {"duration_s": 2.3}   // type-specific, see below
}
```
Payload conventions: `look` → `{"duration_s", "gaze_hit_xyz": [x,y,z]}`; `interest` → `{"duration_s"}`; `bay_issue` → `{"issue": "empty|low_stock|misplaced|label_issue|obstruction|other", "severity": "act_now|act_today|minor|none"}`; `patrol` → `{"state": "TAKEOFF|GOTO_BAY|INSPECT|DECIDE|RETURN|LAND|HOLD", "bay": "bay-B-02"}`.

## REST
| Method | Path | Body / query | Returns |
| --- | --- | --- | --- |
| GET | `/api/health` | | `{"ok": true}` |
| GET | `/api/site` | | `config/site.yaml` as JSON |
| GET | `/api/products` | | `[{product_id,name,brand,barcode,price_gbp,zone_id}]` |
| POST | `/api/events` | Event or `[Event]` | `{"inserted": n, "event_ids": [...]}`; broadcasts each on WS |
| GET | `/api/events` | `type, zone_id, source, since (ISO), limit (default 200)` | `[Event]` newest first |
| GET | `/api/heatmap` | `since` | `{"zones": {"aisle-A-shelf-1": {"look_s": 12.4, "looks": 7}}, "points": [[x,y,z,w], ...]}` |
| GET | `/api/funnel` | `since` | `[{product_id, name, zone_id, passed_by, looked, interested, picked_up, put_back, kept, sold, put_back_rate, flag_high_attention_low_conversion}]` |
| GET | `/api/tasks` | `status` | `[Task]` |
| POST | `/api/tasks` | `{zone_id, kind, severity, source_event, note}` | `Task` (broadcast) |
| PATCH | `/api/tasks/{task_id}` | `{status?, assignee?, note?}` | `Task` (broadcast) |
| GET | `/api/review` | | events whose `decision.policy == "review"` and not yet reviewed |
| POST | `/api/review/{event_id}` | `{"verdict": "confirm"\|"reject", "label"?: str}` | updated Event |
| GET | `/api/drone/state` | | `DroneState` |
| POST | `/api/drone/state` | `DroneState` (pushed by drone/ at ≥2 Hz) | `{"ok": true}` (broadcast) |
| POST | `/api/drone/stop` | | `{"ok": true}`; sets `stop_requested=true` in DroneState; drone/ polls it and LANDs |
| POST | `/api/drone/mission` | `{"bays": ["bay-B-01", ...], "reason": str, "requested_by": "agent"\|"user"}` | `{"accepted": bool, "mission_id", "rejected_reason"?}` — queued for drone/, validated by its safety supervisor |
| GET | `/api/drone/mission` | | the pending/active mission or `null` (drone/ polls this) |
| POST | `/api/ask` | `{"question": str}` | `{"answer": str, "intent": str, "data": any}` — Cactus-style "Ask Sentinel" |
| GET | `/api/summary` | | `{"text": str, "open_tasks": n, ...}` shift summary |

`Task`: `{task_id, created_at, zone_id, kind, severity, status, source_event, assignee, note}`.

`DroneState`: `{"ts", "mode": "sim"|"live", "state": "IDLE|TAKEOFF|GOTO_BAY|INSPECT|DECIDE|RETURN|LAND|HOLD", "x","y","z","yaw_deg", "battery_pct", "current_bay", "last_decision": {...}|null, "stop_requested": bool, "mission_id": str|null, "feed_url": str|null}`.

## WebSocket `/ws`
Server → client JSON messages, one per line/frame:
```json
{"kind": "event",   "data": Event}
{"kind": "task",    "data": Task}
{"kind": "drone",   "data": DroneState}
{"kind": "heatmap", "data": <same as GET /api/heatmap>}   // at most 2 Hz
```

## Replay (hosted read-only dashboard)
The server can record every WS message to `replay/<name>.jsonl` as `{"t": seconds_since_start, "msg": <ws message>}`. The dashboard with `?replay=<url>` plays a JSONL file instead of connecting to `/ws`, and reads `site.json`, `products.json` and the twin from static files. No video is ever uploaded.

## Twin assets (produced by twin/, served statically by the dashboard)
- `twin/out/twin.ply` and `twin/out/twin_points.bin` (Float32 x,y,z,r,g,b interleaved, ≤ 300k points, twin frame) — and/or `twin/out/scene.glb`.
- `twin/out/twin.json`: `{"source": "colmap"|"boxes"|"simready", "point_count", "bounds_min", "bounds_max", "floor_plane"}`.

## Decisions package (`decisions/sentinel_decisions`)
Python, importable by perception/ and drone/ (`pip install -e decisions`). Signatures are fixed; see `decisions/sentinel_decisions/__init__.py`. `SENTINEL_DECISIONS_MOCK=1` returns deterministic fake answers with no network.

## Devin mission agent (`agent/sentinel_agent`)
| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| POST | `/api/agent/run` | `{"goal": str}` (e.g. "end-of-shift stock check") | `{"session_id", "url"}` — server calls `sentinel_agent.launch(goal, api_base)` |
| GET | `/api/agent/runs` | | `[{"session_id","url","goal","status","created_at"}]` |

`sentinel_agent.launch(goal: str, api_base: str) -> dict` creates a Devin session via the Devin API (`DEVIN_API_KEY`). That session is the **mission loop only**: it reads `/api/events`, `/api/tasks`, `/api/drone/state`, then calls `POST /api/drone/mission`, `POST /api/tasks` and posts a summary as an event of `type: "task"`/`source: "agent"`. It never sends flight commands. `api_base` must be publicly reachable (e.g. a `cloudflared` quick tunnel to the laptop).
