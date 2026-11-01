#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: twin/reconstruct.sh <frames-directory> <workspace-directory>" >&2
  exit 2
fi
command -v colmap >/dev/null || { echo 'Install COLMAP: sudo apt-get install colmap' >&2; exit 2; }
command -v timeout >/dev/null || { echo 'GNU timeout is required' >&2; exit 2; }
frames=$(realpath "$1")
mkdir -p "$2"
work=$(realpath "$2")
export QT_QPA_PLATFORM=offscreen
limit=${COLMAP_TIMEOUT_S:-1500}
if [[ ! "$limit" =~ ^[0-9]+$ ]] || (( limit < 1 || limit > 1500 )); then
  echo 'COLMAP_TIMEOUT_S must be 1..1500 (25-minute hard cap)' >&2
  exit 2
fi

# CPU sparse SfM works without CUDA; dense PatchMatch requires CUDA on COLMAP 3.x.
echo "CPU video SfM: sequential matching, one fixed camera, timeout ${limit}s (maximum 25 minutes)."
timeout --signal=TERM --kill-after=10s "${limit}s" colmap automatic_reconstructor \
  --workspace_path "$work" --image_path "$frames" --data_type video \
  --quality medium --single_camera 1 --camera_model SIMPLE_RADIAL \
  --sparse 1 --dense 0 --use_gpu "${COLMAP_USE_GPU:-0}" \
  --num_threads "${COLMAP_THREADS:-4}" 2>&1 | tee "$work/reconstruction.log"

model=$(find "$work/sparse" -mindepth 2 -maxdepth 2 -name points3D.bin -printf '%s %h\n' | sort -nr | head -1 | cut -d' ' -f2-)
if [[ -z "$model" ]]; then
  echo 'COLMAP did not produce a registered model; use the box fallback.' >&2
  exit 3
fi
mkdir -p "$work/model"
colmap model_converter --input_path "$model" --output_path "$work/model" --output_type TXT
colmap model_converter --input_path "$model" --output_path "$work/raw.ply" --output_type PLY
echo "Sparse reconstruction: $work/raw.ply (arbitrary scale; anchor before publishing)"
