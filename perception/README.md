# perception/ — W3 camera perception

Stock-footage "CCTV" camera-1 → YOLO26n-pose tracking → floor position in the twin → head direction
+ gaze cone vs shelf zones → `pass_by` / `look` / `interest` events; wrist-in-shelf reach state machine
→ Decisions API (`holding_product`, `reach_outcome`) → `pick_up` / `put_back` / `kept` events.
Events are POSTed to `$SENTINEL_API/api/events` (default `http://localhost:8000`) and always mirrored to
`perception/out/events.jsonl` (the only output when the server is down).

## Run
```bash
pip install ultralytics opencv-python pyyaml requests numpy && pip install -e decisions
bash perception/fetch_footage.sh                                   # -> perception/footage/aisle.mp4 (+ alt1/alt2)
python -m perception.run --source perception/footage/aisle.mp4 --camera camera-1 --mock   # --show for a window
#   -> perception/out/annotated.mp4, perception/out/events.jsonl, crops/*.jpg
python -m pytest perception/tests -q && ruff check perception
```
Flags: `--mock` sets `SENTINEL_DECISIONS_MOCK=1` (omit it to use the real decisions/ implementation with
`OPENAI_API_KEY`), `--no-post`, `--fps 15` (processing rate, default from site.yaml), `--max-seconds`,
`--weights yolo26n-pose.pt` (falls back to `yolo11n-pose.pt`), `--calib path.json`. `--source 0` or an
`rtsp://` URL also works. CPU only: the 22 s clip processes at 15 fps in ~35 s on 8 cores.

## Modules
| File | What |
| --- | --- |
| `geometry.py` | pinhole `Camera` (K, `T_twin_cam`: OpenCV camera → twin), pixel rays, `ray_plane`, `ray_aabb`, `floor_position()` |
| `pose.py` | QR portal detection (`cv2.QRCodeDetector`, payload = portal id, else the camera's `anchor_portal`) + `solvePnP(SOLVEPNP_IPPE_SQUARE)` → `T_twin_cam` with reprojection error, using site.yaml portal poses |
| `calibrate_manual.py` | 4+ clicked pixel ↔ twin-point pairs → pose via SQPnP + LM refine; with 6+ pairs it also searches the horizontal FOV (approximate pinhole intrinsics). Writes `calib/<camera>.json` + a `.check.jpg` overlay |
| `gaze.py` | keypoint head-yaw, head 3D position, gaze cone (site `gaze_half_angle_deg`, 17 rays) vs shelf zone boxes, `LookTracker` (look ≥ `look_min_s`, interest ≥ `interest_min_s`, 0.6 s dropout tolerance), `PassByTracker` |
| `reach.py` | `ReachMachine`: IDLE → REACHING (before crop) → hold check (`holding_product`) → `pick_up` → CARRYING → `reach_outcome` → `put_back` / `kept` |
| `emit.py` | event sink (POST + jsonl) |
| `run.py` | the runner + annotated video (skeletons, floor point, gaze ray, zone hulls lit on hit, top-down twin inset) |

## Decisions and what is approximate / mocked
- **Footage**: Pexels "Customer Picking Food Items from a Supermarket" (Pexels License; sources + alternates in
  [footage/SOURCES.md](footage/SOURCES.md)). Fixed camera, clear reach-up pick-ups and put-backs, but her
  ankles are hidden by the trolley — no free clip I found had a fixed camera, full body *and* a pick-up.
- **Floor position**: average of the ankle rays ∩ floor plane; one visible ankle is used alone; if both are
  occluded the hip rays are intersected with a plane 0.9 m above the floor and dropped to the floor (this is
  what the stock clip uses); last resort is the person box bottom. Method is shown in the video label.
- **Camera pose**: stock footage has no portal, so `calib/camera-1.json` is a **hand calibration**
  (`calib/camera-1.pairs.json`: 7 hand-picked pixels ↔ *assumed* twin points — the shelf unit in the clip is
  mapped onto aisle-A shelves 1–4, the shopper onto the aisle in front of shelf 3). Reprojection error is
  ~35 px because the clip's real shelf doesn't match the twin's dimensions; it's a plausible mock, not a
  measured pose. The QR/PnP path is used automatically when a portal is visible and no calib file exists.
  Re-calibrate interactively: `python -m perception.calibrate_manual --image perception/footage/aisle_frame.jpg --twin-points "1,2,0;4,2,0;4,2,1.8;1,2,1.8" --pairs perception/calib/camera-1.pairs.json`.
- **Head direction**: keypoint head-yaw estimate (nose offset between ears/shoulders; ears-only = facing
  away; one ear = profile), fixed −12° pitch — **not 6DRepNet360** (skipped for time; the `head_yaw_from_keypoints`
  → `head_direction_twin` seam is where it would plug in).
- **Reach**: wrist (conf ≥ 0.4) inside the image hull of a shelf zone box, arm extended (> 0.55 × torso) and
  above the hip, person within 1 m of the shelf footprint. Product = wrist ray ∩ shelf front plane → slot
  among the zone's 5 SKUs. Outcome is decided when the person leaves the shelf, the track is lost, or 3 s
  after release.
- **Privacy**: faces (head keypoints) are blurred on every crop before it is saved / sent; crops live in
  `crops/` (gitignored); no identities, only short-lived track ids.
- **Decisions**: runs against `sentinel_decisions` as-is; `--mock` gives deterministic answers.
