# drone/ — W6: Sentinel drone patrol (DJI Neo 2 live video + simulated autonomy)

The DJI Neo 2 has **no official SDK**, so we do not fly it from code. The **live** part is its
**video feed** (Android phone running DJI Fly, mirrored to the laptop, see [LIVE_FEED.md](LIVE_FEED.md));
the **autonomous** part (takeoff → bays → decisions → return → land) runs in a kinematic simulator in
the twin frame. Every command passes a code **safety supervisor** first.

## Run

```bash
python -m venv .venv && . .venv/bin/activate
pip install numpy opencv-python-headless pillow pyyaml mss imageio pytest ruff
pip install -e decisions

# 1. Full sim patrol, offline (no server), mock decisions, writes a GIF + per-tick log
SENTINEL_DECISIONS_MOCK=1 python -m drone.run --mode sim --api none \
  --mission bay-B-01,bay-B-02,bay-B-03,bay-B-04 --once --gif drone/out/patrol.gif

# 2. Against the Sentinel server (W1) — or the stdlib stand-in: python -m drone.devserver --port 8000
python -m drone.run --mode sim --api http://localhost:8000          # polls GET /api/drone/mission
curl -X POST localhost:8000/api/drone/mission -H 'Content-Type: application/json' \
  -d '{"bays":["bay-B-02","bay-B-03"],"reason":"stock check","requested_by":"user"}'
curl -X POST localhost:8000/api/drone/stop                           # STOP -> LAND

# 3. Live Neo 2 video (Android + scrcpy, see LIVE_FEED.md); position = portal PnP if visible, else sim estimate
python -m drone.run --mode live --source 10 --crop 0.1,0.08,0.8,0.84       # Linux v4l2 sink /dev/video10
python -m drone.run --mode live --source screen:0,40,1280,720              # macOS: scrcpy window region

# Tests + lint
SENTINEL_DECISIONS_MOCK=1 pytest drone/tests -q && ruff check drone
```

Useful flags: `--hz 20` (flight loop 10–30 Hz), `--people 6,5@8` (sim: inject a person at (6,5) after 8 s →
HOLD), `--battery 35` (sim: low battery → return/land), `--max-s 60`.

## Files

| File | What |
| --- | --- |
| `driver.py` | `DroneDriver` ABC (`takeoff/land/send_velocity/video_frames/telemetry`), `Telemetry`, `Frame`, `NotSupported` |
| `sim.py` | `SimDriver`: first-order kinematic sim in the twin frame, battery drain, synthetic rack-bay images (bay-B-02 empty pick face, bay-B-03 misplaced blue tote) |
| `live.py` | `LiveFeedDriver` (video only: device index / rtmp:// / file / `screen:L,T,W,H` via mss, `crop`, portal QR PnP fix; flight methods raise `NotSupported`), `NeoDriver`/`TelloDriver` stubs |
| `safety.py` | `SafetySupervisor` — STOP, battery, lost fix, lost link, geofence, people distance, max alt, max speed; mission + advisory-action validation |
| `patrol.py` | State machine `IDLE→TAKEOFF→GOTO_BAY→INSPECT→DECIDE→…→RETURN→LAND`, `HOLD` on decision timeout / person too close |
| `decide.py` | Decision worker thread: `bay_issue` → `issue_severity` → `drone_next_action` (from `sentinel_decisions`) |
| `api.py` | Network thread: polls stop flag + mission, POSTs DroneState at 3 Hz, events and tasks |
| `run.py` | CLI / flight loop; `viz.py` renders the GIF; `devserver.py` stdlib stand-in for the W1 drone endpoints |
| `scripts/` | `scrcpy_mirror.sh`, `rtmp_server.sh` (mediamtx), `test_pattern.sh`, `list_sources.py`, `preview.py` |

## Threads (no AI or network inside the flight loop)

- **Flight loop** (`run.py`, 20 Hz): `SimDriver.step` → `Patrol.tick` → `SafetySupervisor.check` → `send_velocity`.
  It only reads in-memory snapshots and appends to an outbox.
- **Decision worker** (`decide.py`): Decisions API calls. If no answer within `decision_timeout_s` (2 s) the
  drone HOLDs and logs `unclear`; it resumes when the answer lands, or skips the bay after 8 s.
- **Link** (`api.py`): all HTTP. Server down = drone still flies the local mission; link lost > 5 s after
  being up → LAND.

## Safety rules (each has a failing-scenario test in `tests/test_safety.py` / `tests/test_patrol.py`)

| Rule | Source (config/site.yaml `drone:`) | Effect |
| --- | --- | --- |
| STOP flag (`GET /api/drone/state` `stop_requested`) | dashboard | LAND (latched) |
| battery < `min_battery_pct` (30) | | LAND (latched); < 40 % → advisory actions become `return_home` |
| no position fix > `lost_fix_land_s` (2 s) | | LAND (latched) |
| outside `geofence_polygon_xy` / > `max_alt_m` + 0.5 | | LAND (latched) |
| person within `min_dist_people_m` (3 m) | | HOLD, resume when clear |
| command would leave geofence (0.5 s look-ahead) | | horizontal velocity zeroed |
| command would exceed `max_alt_m` (4 m) | | climb zeroed |
| speed > `max_speed_mps` (1 m/s), yaw > 90°/s | | scaled down |
| `drone_next_action` advisory | Decisions API | validated (`move_closer` target in fence, 1 rescan max, unknown → `return_home`) |

Guardrails: never modify firmware; never disable or bypass DJI obstacle sensing, geofencing, altitude/speed
limits or return-to-home; our supervisor sits on top of DJI's, never in place of it.

## What is mocked

- **Flight**: simulated (the human pilots the real Neo 2). In live mode DroneState carries
  `"piloted": true, "flight": "piloted"` (extra fields beyond the contract) so the dashboard can label
  the drone as human-flown; sim mode sends `"piloted": false, "flight": "sim"`. Live mode shows the portal PnP position when a
  portal QR is in view, else the sim estimate (`fix_source` = `portal` / `estimate` in DroneState).
- **Decisions in mock mode** (`SENTINEL_DECISIONS_MOCK=1`): the mock always answers `ok`, so in **sim** the
  simulator's ground truth is substituted and labelled `answer.type = "sim_truth"`. With real decisions the
  synthetic bay images are sent to the Decisions API as-is.
- **People detections**: injected with `--people` (no YOLO here).
- **Mission completion**: the contract has no "mission done" endpoint; drone/ posts DroneState
  `state: IDLE, mission_id: null` and a `patrol` event with `state: LAND`, and never re-runs a mission id it finished.
