#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p "$root/twin/work"
echo 'Tiger Lily / Pexels: Man Working inside the Warehouse (4292299)'
echo 'Source: https://www.pexels.com/video/man-working-inside-the-warehouse-4292299/'
echo 'Licence: https://www.pexels.com/license/ (not an endorsement; local test input only)'
curl --fail --location --retry 2 --max-time 90 \
  'https://videos.pexels.com/video-files/4292299/4292299-hd_1920_1080_25fps.mp4' \
  --output "$root/twin/work/warehouse.mp4"
echo "Downloaded locally: $root/twin/work/warehouse.mp4"
