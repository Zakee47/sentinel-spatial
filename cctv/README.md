# cctv/ — CCTV camera ingestion (W10)

Makes the fixed camera a real CCTV feed for `perception/` (unchanged) and the dashboard.

| file | what |
|---|---|
| `sources.py` | `open_source(uri)` → threaded latest-frame OpenCV capture: `rtsp://`, `rtsps://`, `rtmp://`, MJPEG over `http(s)`, HLS `.m3u8`, files, device index. FFmpeg backend with `rtsp_transport;tcp` + low-latency flags, stale frames dropped, auto-reconnect with exponential backoff (0.5 s → 30 s), health stats (fps, last frame age, drops, reconnects). `${VAR}` placeholders in URIs are filled from env and URL-encoded; URIs are redacted in logs. |
| `run_perception.py` | Runs `perception.run` against a camera id/URI with the TCP/low-latency FFmpeg options set. (`perception.run --source` already takes RTSP URLs; this adds config lookup + credentials.) |
| `snapshot_server.py` | FastAPI on :8090 — `/cameras`, `/cameras/<id>/snapshot.jpg`, `/cameras/<id>/mjpeg`, `/health`. CORS open (GET). |
| `onvif_discover.py` | WS-Discovery probe for ONVIF cameras on the LAN; `--ip` fetches RTSP + snapshot URIs per profile via `onvif-zeep`. |
| `mock_cctv.sh` | Starts `mediamtx` (downloaded to `cctv/bin/`) and loops footage with a burnt-in CCTV timestamp to `rtsp://localhost:8554/camera-1`. |
| `fetch_cctv_footage.sh` | Downloads the real CCTV clip (below) with `yt-dlp` to `cctv/footage/cctv_retail.mp4`. |
| `cameras.example.yaml` | camera id → URI. Copy to `cameras.local.yaml` (gitignored) for real cameras. |

## Run (demo)

```bash
pip install opencv-python-headless numpy pyyaml fastapi uvicorn yt-dlp   # + perception's deps
bash cctv/fetch_cctv_footage.sh            # real CCTV clip (falls back to perception/footage/aisle.mp4)
bash cctv/mock_cctv.sh &                   # rtsp://localhost:8554/camera-1
python -m perception.run --source rtsp://localhost:8554/camera-1 --camera camera-1 --mock
#   or: python -m cctv.run_perception --camera camera-1 -- --mock
python -m cctv.snapshot_server             # http://localhost:8090/cameras/camera-1/snapshot.jpg
python -m cctv.onvif_discover              # find real cameras on the LAN
ONVIF_USER=admin ONVIF_PASS=... python -m cctv.onvif_discover --ip 192.168.1.64
pytest cctv/tests && ruff check cctv
```

Footage: "E43A inside the Retail store in USA #2" (ACTi 5MP bullet camera), https://www.youtube.com/watch?v=-1bRhYjw1qE — standard YouTube licence, **downloaded locally only, never committed** (`cctv/footage/` is gitignored).

## Real cameras

Put credentials in env and reference them in `cctv/cameras.local.yaml`:

```yaml
cameras:
  - id: camera-1
    uri: rtsp://${CAM1_USER}:${CAM1_PASS}@192.168.1.64:554/Streaming/Channels/101
```

Common RTSP URL patterns (main stream / sub stream; sub streams are lighter for perception):

| vendor | URL |
|---|---|
| Hikvision | `rtsp://user:pass@IP:554/Streaming/Channels/101` (main), `/102` (sub); snapshot `http://IP/ISAPI/Streaming/channels/101/picture` |
| Dahua / Amcrest | `rtsp://user:pass@IP:554/cam/realmonitor?channel=1&subtype=0` (main), `subtype=1` (sub); snapshot `http://IP/cgi-bin/snapshot.cgi` |
| Reolink | `rtsp://user:pass@IP:554/h264Preview_01_main`, `_sub` (RTSP must be enabled in app) ; newer: `/Preview_01_main` |
| Axis | `rtsp://user:pass@IP/axis-media/media.amp` (`?resolution=1280x720`); MJPEG `http://IP/axis-cgi/mjpg/video.cgi` |
| Uniview | `rtsp://user:pass@IP:554/unicast/c1/s0/live` (main), `s1` (sub); older `/media/video1` |
| TP-Link Tapo | `rtsp://user:pass@IP:554/stream1` (main), `/stream2` (sub) — "camera account" created in the Tapo app |
| ACTi | `rtsp://user:pass@IP:7070/stream1` (or `/track1`) |

ONVIF port is usually 80 (Hikvision/Dahua/Axis), 8000 (Reolink) or 2020 (Tapo).

## Integration notes

- **Dashboard (W5):** point a camera tile at `http://<host>:8090/cameras/camera-1/mjpeg` (an `<img src>` works) or poll `/snapshot.jpg`. `/cameras` returns `feed_url`/`snapshot_url` per camera, matching the `feed_url` naming in `DroneState`.
- **More fixed cameras:** add an entry under `cameras:` in `config/site.yaml` (`id: camera-2`, `kind: fixed`, `url: rtsp://...` or a `cameras.local.yaml` id, `anchor_portal`, `fps`), a calibration `perception/calib/camera-2.json`, and a matching line in `cctv/cameras.local.yaml`; then run one `perception.run --camera camera-2` per camera. Not edited here (fixed contract).
- Credentials only from env / gitignored `cameras.local.yaml`.
