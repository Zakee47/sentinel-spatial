#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python=${PYTHON:-"$root/.venv/bin/python"}

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo 'Usage: scripts/drone_twin.sh <clip.mp4|frames-dir> [survey.json]' >&2
  exit 2
fi
capture=$("$python" -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).expanduser().resolve())' "$1")
if [[ -d "$capture" ]]; then
  "$python" - "$capture" <<'PY'
import pathlib, sys
images = [path for path in pathlib.Path(sys.argv[1]).iterdir()
          if path.suffix.lower() in {'.jpg', '.jpeg', '.png'}]
if not images:
    raise SystemExit(f"Frame directory contains no JPG or PNG images: {sys.argv[1]}")
PY
  depth_input="$capture"
elif [[ -f "$capture" ]]; then
  depth_input="$capture"
else
  echo "Clip or frame directory not found: $capture" >&2
  exit 2
fi
survey=${2:-}
if [[ -n "$survey" ]]; then
  survey=$("$python" -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).expanduser().resolve())' "$survey")
  [[ -f "$survey" ]] || { echo "Survey not found: $survey" >&2; exit 2; }
fi

out=${TWIN_OUT_DIR:-"$root/twin/out"}
depth_out=${DEPTH_OUT_DIR:-"$root/depth/out"}
publish=${DRONE_TWIN_PUBLISH:-1}
start=$SECONDS
cd "$root"

if [[ -n "$survey" ]]; then
  PYTHON="$python" TWIN_OUT_DIR="$out" bash twin/build.sh "$capture" "$survey"
else
  PYTHON="$python" TWIN_OUT_DIR="$out" bash twin/build.sh "$capture"
fi

meta="$out/twin.json"
[[ -s "$meta" ]] || { echo "Twin build did not produce $meta" >&2; exit 1; }
workspace=$("$python" -c 'import json,sys; print(json.load(open(sys.argv[1]))["workspace"])' "$meta")
source=$("$python" -c 'import json,sys; print(json.load(open(sys.argv[1]))["source"])' "$meta")
depth_tmp="$workspace/depth-output"
depth_work="$workspace/depth-work"
mkdir -p "$depth_tmp" "$depth_work"

depth_args=(--out "$depth_tmp" --work "$depth_work" --max-frames "${DRONE_TWIN_DEPTH_FRAMES:-3}"
  --max-width "${DRONE_TWIN_DEPTH_WIDTH:-640}" --stride "${DRONE_TWIN_DEPTH_STRIDE:-3}")
depth_mode=assumed_camera_pose
if [[ "$source" == colmap && -s "$workspace/T_twin_colmap_final.json" ]]; then
  if "$python" -m depth.video_depth "$workspace/frames" \
    --colmap "$workspace/colmap/model" \
    --twin-transform "$workspace/T_twin_colmap_final.json" \
    "${depth_args[@]}"; then
    depth_mode=twin_transform
  else
    echo 'COLMAP depth fusion failed; retrying as assumed_camera_pose (not site-registered).' >&2
    depth_tmp="$workspace/depth-assumed-output"
    depth_work="$workspace/depth-assumed-work"
    mkdir -p "$depth_tmp" "$depth_work"
    depth_args=(--out "$depth_tmp" --work "$depth_work" --max-frames "${DRONE_TWIN_DEPTH_FRAMES:-3}"
      --max-width "${DRONE_TWIN_DEPTH_WIDTH:-640}" --stride "${DRONE_TWIN_DEPTH_STRIDE:-3}")
    "$python" -m depth.video_depth "$depth_input" --no-colmap "${depth_args[@]}"
  fi
else
  echo 'No successful COLMAP metric alignment; publishing depth with assumed_camera_pose.' >&2
  "$python" -m depth.video_depth "$depth_input" --no-colmap "${depth_args[@]}"
fi

"$python" - "$meta" "$depth_tmp/depth.json" "$depth_mode" <<'PY'
import json, pathlib, sys
twin = json.loads(pathlib.Path(sys.argv[1]).read_text())
path = pathlib.Path(sys.argv[2])
depth = json.loads(path.read_text())
depth['alignment_provenance'] = twin.get('alignment_provenance', 'unregistered')
if twin.get('registration') == 'example_alignment' and depth.get('registration') == 'twin_transform':
    depth['registration'] = 'example_alignment'
    for frame in depth.get('frames', []):
        if frame.get('registration') == 'twin_transform':
            frame['registration'] = 'example_alignment'
if sys.argv[3] == 'assumed_camera_pose' or depth.get('registration') != 'twin_transform':
    depth['metric_registration'] = False
else:
    depth['metric_registration'] = twin.get('metric_registration', False)
path.write_text(json.dumps(depth, indent=2) + '\n')
PY

mkdir -p "$depth_out"
cp "$depth_tmp/depth_points.bin" "$depth_tmp/depth.json" "$depth_out/"

if [[ "$publish" != 0 ]]; then
  twin_public="$root/dashboard/public/twin/out"
  depth_public="$root/dashboard/public/depth/out"
  mkdir -p "$twin_public" "$depth_public"
  cp "$out/twin_points.bin" "$out/twin.json" "$twin_public/"
  if [[ -f "$out/scene.glb" ]]; then
    cp "$out/scene.glb" "$twin_public/"
  else
    rm -f "$twin_public/scene.glb"
  fi
  cp "$depth_tmp/depth_points.bin" "$depth_tmp/depth.json" "$depth_public/"
fi

"$python" - "$meta" "$depth_tmp/depth.json" "$workspace" "$SECONDS" "$start" <<'PY'
import json, pathlib, sys
twin = json.loads(pathlib.Path(sys.argv[1]).read_text())
depth = json.loads(pathlib.Path(sys.argv[2]).read_text())
registered = 0
model = pathlib.Path(sys.argv[3]) / 'colmap/model/images.txt'
if model.exists():
    registered = sum(
        1 for line in model.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    ) // 2
print(json.dumps({
    'twin_source': twin.get('source'),
    'twin_registration': twin.get('registration'),
    'twin_points': twin.get('point_count'),
    'registered_images': registered,
    'scale_rmse_m': (twin.get('alignment') or {}).get('rmse_m'),
    'depth_points': depth.get('n_points'),
    'depth_registration': depth.get('registration'),
    'runtime_s': int(sys.argv[4]) - int(sys.argv[5]),
    'workspace': sys.argv[3],
}, indent=2))
PY
if [[ "$publish" != 0 ]]; then
  echo "Dashboard assets published under dashboard/public/{twin,depth}/out/"
else
  echo 'DRONE_TWIN_PUBLISH=0; dashboard asset copy skipped.'
fi
