# Sentinel depth / LiDAR (W9)

**Video depth is real model inference, not measured LiDAR.** The DJI Neo 2's
obstacle sensors are not exposed by DJI Fly or a supported SDK. This work does
not extract/decrypt their data, change firmware, bypass obstacle sensing,
geofencing, speed/altitude limits or return-to-home, or put AI/network requests
in a flight-control loop. Zak's Android phone has no LiDAR. A real scan must
come from a separate scanner, a borrowed LiDAR-equipped device, an existing
Polycam/Scaniverse export, or a future LiDAR-equipped drone.

All commands below run from the **repository root**, using Python 3.11+.
Everything this workstream creates lives under `depth/`.

## Install

```sh
python -m pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r depth/requirements.txt
```

CPU inference; first run downloads the ~100 MB model from Hugging Face to its
normal user cache (not the repository). No API keys needed. Open3D is a large
optional runtime dependency used only for PLY/PCD/meshes; LAS/LAZ use laspy +
lazrs. E57 additionally needs `python -m pip install pye57` (libE57 wheels are
platform-dependent). If unavailable, export E57 to PLY with CloudCompare first.

## One-command warehouse video demo

```sh
curl -L --fail https://videos.pexels.com/video-files/4294436/4294436-hd_1920_1080_25fps.mp4 -o depth/warehouse.mp4 && python -m depth.video_depth depth/warehouse.mp4 --no-colmap
```

The checked-in demo uses frames at 0, 2 and 4 seconds from **Tiger Lily, A
Footage inside the Warehouse**:
https://www.pexels.com/video/a-footage-inside-the-warehouse-4294436/
(11-second stock video, **Pexels License**, free use and modification:
https://www.pexels.com/license/). No endorsement implied. Original video and
intermediate depth arrays are gitignored; only small transformed clouds are
committed. This is stock warehouse footage, not Zak's live warehouse/drone.

```sh
python -m depth.video_depth /path/to/drone-video.mp4 --max-frames 5 --every-s 1
python -m depth.bay_fill > depth/out/bay_fill.json
python -m depth.render_cloud --image depth/work/frames/frame_000002.jpg --depth depth/work/frame_000002_depth.npy
```

Default output: `depth/out/depth_points.bin`, `depth.ply`, `depth.json`.
Without poses, each frame is exported independently to `frame_000000/`, etc.;
the root cloud is the **last processed frame**, never a fake multi-view fusion.
`fused_frames: 0` records this. A single-frame run writes just the root assets.

### What's real vs approximated

* Real: CPU `transformers.pipeline('depth-estimation')` using
  `depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf`; numeric
  `predicted_depth`, not its 8-bit display image; RGB back-projection; voxel
  reduction; binary/PLY export. Model card:
  https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf
* Approximated: when calibration is absent, **90° horizontal FOV**, centred
  principal point, square pixels, zero lens distortion. This is a conservative
  Neo-style pinhole assumption, **not a factory Neo 2 calibration**. Cropping,
  digital stabilisation, tilt and lens distortion can cause large errors.
  Override `--hfov-deg`, or `--intrinsics calibration.json` with
  `{"width":1920,"height":1080,"fx":960,"fy":960,"cx":959.5,"cy":539.5}`.
* Approximate display pose without COLMAP: camera 1.5 m above origin, X forward,
  Y left, Z up. This does **not** establish warehouse/portal alignment. Floors
  may be tilted/negative because real camera pitch is unknown.
* Learned indoor metric depth is an estimate, not survey-grade distance.
  Warehouses can exceed its indoor training range. Accuracy is unvalidated.
* If the metric checkpoint cannot load, the relative Small model is tried;
  inverse relative predictions are normalised to an **assumed 5 m median**.
  `--relative-scale-m` changes it. `--relative` explicitly exercises this path.
  Metadata always labels relative mode. If both models fail, the command fails;
  there is no synthetic depth masquerading as real inference.

## COLMAP multi-view fusion

Auto-discovery searches `twin/work/**/sparse/0` and `**/sparse`. For reliable
frame association, pass **the same image directory W4 reconstructed**, with
unchanged filenames (and preferably COLMAP-undistorted PINHOLE cameras):

```sh
python -m depth.video_depth twin/work/frames --colmap twin/work/model/sparse/0 --max-frames 20 --colmap-unit-m 1 --twin-transform depth/alignment-transform.json
```

Both `cameras/images/points3D.txt` and COLMAP binary equivalents are read by a
small local parser. Quaternion + translation are world-to-camera as COLMAP
specifies; back-projection uses camera intrinsics scaled to inference size.
For each registered frame, scale is the robust median of
`COLMAP sparse camera-Z / predicted depth` at sparse correspondences (>=3).
Depth is corrected before camera-to-world fusion. Distortion parameters are
read but **not applied**; use undistorted images/models for accurate fusion.

COLMAP alone is arbitrary-scale and does **not** establish the site frame.
W4 must supply known `--colmap-unit-m` (default 1, an explicit assumption) and
an optional JSON 4×4 matrix `T_twin_colmap`, applied **after** scale to metres.
Without that matrix, metadata says `colmap_frame_unregistered` and bay fills
remain unavailable. A mismatched/unregistered frame is exported separately,
never fused. An invalid sparse model/insufficient scale correspondences fails
clearly rather than silently inventing a scale.

## Real scan ingestion

```sh
python -m depth.ingest_scan /path/to/scan.ply
python -m depth.ingest_scan /path/to/scan.laz --unit-m 1 --alignment depth/alignment-example.json
python -m depth.ingest_scan /path/to/mesh.glb --up y
```

Supported: `.ply`/`.pcd` (Open3D), `.las`/`.laz` (laspy/lazrs), `.e57`
(optional pye57; all scans and stored scanner transforms), `.obj`/`.glb`/`.gltf`
(uniformly sample 200k mesh surface points; not new measurements).

Units must be known: `--unit-m 0.001` for millimetres; default metres. A
gravity-constrained floor RANSAC rejects walls/ceilings, rotates the floor to
Z-up, translates it to z=0; `--up x|y|z` selects the input gravity axis. If the
floor is not visible, fitting fails rather than silently using a wall. Floor
alignment alone does **not** locate the scan in the site (XY/yaw unknown).

Optional correspondence JSON (pick >=3 **non-collinear** points in the original
scan and the matching known twin points, in site metres):

```json
{"scan_points": [[0,0,0],[2.5,0,0],[0,1.2,0]],
 "twin_points": [[0,8,0],[2.5,8,0],[0,9.2,0]]}
```

These illustrative twin targets are corners of `bay-B-01` from
`config/site.yaml`; **replace scan_points with actual picked measurements**.
Rigid Kabsch alignment follows floor alignment; no unrequested scale/reflection.
RMSE and the final transform are saved. Bad picks can defeat the floor fit;
inspect RMSE and the rendered cloud. No scanner file or site alignment was
provided for this demo; scan imports are covered with generated fixtures, not
claimed as a real LiDAR capture.

## Dashboard assets / integration

`depth_points.bin`: **little-endian Float32 x,y,z,r,g,b**, RGB in **[0,1]**,
24 bytes per point, no header, <=300k points. `depth.ply`: matching binary PLY
with RGB bytes. Finite points only, deterministic voxel representative;
voxel size is increased until the point cap is met (default 5 cm).

Metadata has `{source,n_points,bbox:{min,max},voxel_m,frame:"twin"}` plus
dashboard aliases `point_count,bounds_min,bounds_max`, registration/model/
provenance information. `frame:"twin"` denotes output axis convention; **only
`registration:"twin_transform"` or `"point_correspondences"` confirms actual
site placement**. Do not treat an assumed local camera frame as site truth.
No fixed contracts or W4/dashboard files were changed: the integrator can load
these assets like the contract's `twin_points.bin` or expose them separately.

## Bay fill signal (not stock judgement)

```sh
python -m depth.bay_fill depth/out/depth_points.bin --voxel-m 0.2
```

Uses each `kind: rack_bay` polygon and z-range from the fixed site config.
`fill_pct` = occupied voxels / bay voxels × 100, not raw point count and not
true solid-volume fill. Voxel size materially changes this proxy. Boundary
faces are half-open to avoid double-counting adjoining bays. **Unseen space
is unknown, not empty**, and sparse surface returns cannot establish stock
volume. Registration is required: otherwise `fill_pct:null`. `--registered`
is an explicit operator assertion for a cloud already independently aligned.
This is an extra observation for the Decisions API, never an automatic
low-stock/empty verdict. The stock-video demo deliberately returns null bay
fills because it has no relationship to the site's rack positions.

## Checks

```sh
python -m pytest depth/tests -q
ruff check depth
ruff format --check depth
mypy --ignore-missing-imports depth
```

Tests use small generated fixtures: pinhole back-projection, floor RANSAC,
rigid alignment, bay occupancy/boundaries, export cap/colour range, COLMAP
text/binary reads, scale/pose transforms and scan-format round-trips. Network
model downloads are not part of pytest. The checked-in clouds + screenshot
are from an actual separate CPU inference run on the credited stock clip.
