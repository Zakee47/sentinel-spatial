#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python=${PYTHON:-"$root/twin/.venv/bin/python"}
out=${TWIN_OUT_DIR:-"$root/twin/out"}
if [[ "$out" != /* ]]; then out="$root/$out"; fi
out=$("$python" -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "$out")
if [[ ! -x "$python" ]] && ! command -v "$python" >/dev/null; then
  echo 'Setup: python3 -m venv twin/.venv && twin/.venv/bin/pip install -r twin/requirements-reconstruction.txt' >&2
  exit 2
fi
if [[ ${1:-} == --boxes ]]; then
  [[ $# -eq 1 ]] || { echo 'Usage: twin/build.sh --boxes' >&2; exit 2; }
  cd "$root"
  "$python" -m twin.boxes --out "$out"
  "$python" -m twin.render --input "$out/twin_points.bin" --out "$out/preview.png"
  exit 0
fi
if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo 'Usage: twin/build.sh <video.mp4|frames-dir> [alignment.json] | --boxes' >&2
  exit 2
fi
input=$("$python" -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).expanduser().resolve())' "$1")
video=""
frames_source=""
if [[ -d "$input" ]]; then
  frames_source="$input"
  "$python" - "$frames_source" <<'PY'
import pathlib, sys
images = [path for path in pathlib.Path(sys.argv[1]).iterdir()
          if path.suffix.lower() in {'.jpg', '.jpeg', '.png'}]
if not images:
    raise SystemExit('Frame directory contains no JPG or PNG images')
PY
elif [[ -f "$input" ]]; then
  video="$input"
else
  echo "Video or frame directory not found: $input" >&2
  exit 2
fi
alignment=${2:-${TWIN_ALIGNMENT:-}}
if [[ -n "$alignment" ]]; then
  alignment=$("$python" -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).expanduser().resolve())' "$alignment")
  [[ -f "$alignment" ]] || { echo "Alignment not found: $alignment" >&2; exit 2; }
fi
cd "$root"
mkdir -p twin/work
work=$(mktemp -d "$root/twin/work/capture-XXXXXX")
echo "Working directory: $work"

fallback() {
  echo 'Reconstruction or metric alignment unavailable; exporting clearly-labelled box fallback.' >&2
  "$python" -m twin.boxes --out "$out"
  "$python" -m twin.render --input "$out/twin_points.bin" --out "$out/preview.png"
  "$python" - "$work" "$out" <<'PY' || return
import json, pathlib, sys
path = pathlib.Path(sys.argv[2])/'twin.json'
data = json.loads(path.read_text())
data['fallback_reason'] = 'Capture pipeline failed; inspect the local build.log. No metric scale was invented.'
data['workspace'] = str(pathlib.Path(sys.argv[1]).resolve())
data['registration'] = 'synthetic_box'
data['metric_registration'] = False
path.write_text(json.dumps(data, indent=2)+'\n')
print('Box fallback ready. Raw footage and diagnostics remain local:', sys.argv[1])
PY
  cat <<NEXT

NEXT STEPS — the published assets are SYNTHETIC (source=boxes), not a metric scan.
1. Check the error above, $work/build.log, and $work/frames.json.
2. If raw.ply exists, keep it: COLMAP completed but still needs metric anchoring.
   QR route: film measured QR portals P0/P1/P2/P3 (or sentinel:P1) from multiple views.
   Manual route: pick >=3 non-collinear points in $work/colmap/raw.ply and survey
   their twin XYZ positions in metres. Write {"pairs":[{"colmap":[x,y,z],"twin":[X,Y,Z]},...]}.
   Then resume WITHOUT re-running COLMAP (replace /path/to/my-survey.json):
   $python -m twin.anchor "$work/colmap/raw.ply" --alignment /path/to/my-survey.json --out "$work/anchored.npy"
   $python -m twin.floor "$work/anchored.npy" --out "$work/floored.npy"
   $python -m twin.export "$work/floored.npy" --out twin/out
   rm -f twin/out/scene.glb
   $python -m twin.render
See twin/README.md for filming and measured-portal placement. No scale was invented.
NEXT
}

pipeline() {
  if [[ -n "$frames_source" ]]; then
    ln -s "$frames_source" "$work/frames" || return
    "$python" - "$frames_source" "$work/frames.json" <<'PY' || return
import json, pathlib, sys
frames_dir = pathlib.Path(sys.argv[1])
paths = sorted(path for path in frames_dir.iterdir()
               if path.suffix.lower() in {'.jpg', '.jpeg', '.png'})
record_path = frames_dir.parent / 'record.json'
record = json.loads(record_path.read_text()) if record_path.is_file() else {}
interval = record.get('record_every_s')
report = {
    'input': record.get('source', str(frames_dir)),
    'fps': None,
    'sample_fps': 1 / interval if interval else None,
    'duration_s': record.get('duration_s'),
    'max_width': None,
    'frame_count': len(paths),
    'sampled_count': len(paths),
    'blur_threshold': None,
    'rejected_count': 0,
    'frames': [{'name': path.name, 'accepted': True} for path in paths],
    'video_uploaded': False,
}
pathlib.Path(sys.argv[2]).write_text(json.dumps(report, indent=2) + '\n')
PY
  else
    "$python" -m twin.extract_frames "$video" --out "$work/frames" \
      --fps "${TWIN_FPS:-2}" --max-frames "${TWIN_MAX_FRAMES:-160}" \
      --max-width "${TWIN_MAX_WIDTH:-1600}" --blur-threshold "${TWIN_BLUR_THRESHOLD:-50}" || return
  fi
  PYTHON="$python" bash twin/reconstruct.sh "$work/frames" "$work/colmap" || return
  local anchor_args=(--model "$work/colmap/model" --images "$work/frames")
  if [[ -n "$alignment" ]]; then anchor_args=(--alignment "$alignment"); fi
  "$python" -m twin.anchor "$work/colmap/raw.ply" "${anchor_args[@]}" --out "$work/anchored.npy" || return
  "$python" -m twin.floor "$work/anchored.npy" --out "$work/floored.npy" || return
  # Stage complete assets before replacing the published set; stale scene.glb must
  # not silently replace a successful COLMAP cloud in a dashboard preferring GLB.
  "$python" -m twin.export "$work/floored.npy" --out "$work/out" --source colmap || return
  "$python" - "$work" "$out" "$alignment" <<'PY' || return
import json, pathlib, shutil, sys
work = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
alignment = pathlib.Path(sys.argv[3]) if sys.argv[3] else None
meta_path = work/'out/twin.json'
meta = json.loads(meta_path.read_text())
meta['units'], meta['up_axis'], meta['synthetic'] = 'metres', 'Z', False
anchor = json.loads((work/'anchored.json').read_text())
floor = json.loads((work/'floored.json').read_text())
import numpy as np
transform = np.asarray(floor['T_floor_refinement']) @ np.asarray(anchor['T_twin_colmap'])
example_alignment = bool(
    alignment and 'EXAMPLE ONLY' in alignment.read_text().upper()
)
meta['workspace'] = str(work.resolve())
meta['alignment'] = anchor
meta['floor_refinement'] = floor
meta['T_twin_colmap_final'] = transform.tolist()
meta['registration'] = 'example_alignment' if example_alignment else 'twin_transform'
meta['metric_registration'] = not example_alignment
meta['alignment_provenance'] = (
    'example_only' if example_alignment
    else 'operator_supplied' if alignment
    else 'portal_or_qr'
)
meta['frame_sampling'] = json.loads((work/'frames.json').read_text())
meta['matching'] = 'sequential'
meta_path.write_text(json.dumps(meta, indent=2)+'\n')
(work/'T_twin_colmap_final.json').write_text(
    json.dumps(transform.tolist(), indent=2)+'\n'
)
out.mkdir(exist_ok=True)
for name in ('twin.json', 'twin.ply', 'twin_points.bin'):
    shutil.copy2(work/'out'/name, out/name)
(out/'scene.glb').unlink(missing_ok=True)
(out/'preview.png').unlink(missing_ok=True)
PY
  "$python" -m twin.render --input "$out/twin_points.bin" --out "$out/preview.png" || return
}

if pipeline 2>&1 | tee "$work/build.log"; then
  echo "COLMAP twin published in $out/"
else
  fallback
fi
