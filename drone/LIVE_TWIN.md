# Live flight recording and twin build

Sentinel reads DJI Fly video; it does **not** pilot the Neo 2. Keep DJI Fly's
flight protections enabled and have a human pilot control and land the aircraft.
The local patrol state and API STOP do not send flight commands to the Neo 2.

## One-time laptop setup

From the repository root, run:

```bash
bash scripts/laptop_setup.sh
```

On macOS this uses Homebrew; on Linux it uses `apt-get` and may ask for `sudo`.
It checks/installs `adb`, `scrcpy`, FFmpeg, COLMAP, Python, Node, a CPU PyTorch
environment, and the repository's drone-live, depth, and twin Python
requirements. If the setup script reports missing items, install them as shown
and rerun it. Android **USB debugging** must also be enabled on the phone and
the laptop authorized in the Android prompt.

## Start API, database, and dashboard

Terminal 1, from the repository root:

```bash
SENTINEL_DECISIONS_MOCK=1 SENTINEL_AGENT_MOCK=1 docker compose up -d --build
curl -fsS http://localhost:8000/api/health
```

Terminal 2:

```bash
cd dashboard
npm ci
npm run dev
```

Open <http://localhost:5173>. The Vite dev server proxies `/api` and `/ws` to
the local API. Keep both services running while capturing and building.

## Android DJI Fly → USB scrcpy

Connect the Android phone by USB, unlock it, accept the debugging prompt, open
the DJI Fly camera view, and keep the phone in landscape. Confirm the phone is
authorized:

```bash
adb devices
```

### Linux: V4L2 camera source

Create the virtual camera once after setup or reboot:

```bash
sudo modprobe v4l2loopback video_nr=10 card_label=scrcpy exclusive_caps=1
bash drone/scripts/scrcpy_mirror.sh --device /dev/video10
```

Run Sentinel in another terminal, replacing the recording directory as needed:

```bash
recording="$HOME/sentinel-runs/zak-$(date +%Y%m%d-%H%M%S)"
.venv/bin/python -m drone.run \
  --mode live --source 10 --api http://localhost:8000 \
  --record "$recording" --record-every 0.5 --build-twin-on-land
```

If V4L2 is unavailable, use scrcpy's window and the screen-capture command
below instead.

### macOS: capture the scrcpy window

Start scrcpy in a terminal:

```bash
bash drone/scripts/scrcpy_mirror.sh
```

Grant Terminal/Python Screen Recording permission if macOS asks. Set
`LEFT,TOP,WIDTH,HEIGHT` to the screen rectangle containing the DJI Fly view;
coordinates are pixels:

```bash
recording="$HOME/sentinel-runs/zak-$(date +%Y%m%d-%H%M%S)"
.venv/bin/python -m drone.run \
  --mode live --source screen:LEFT,TOP,WIDTH,HEIGHT --api http://localhost:8000 \
  --record "$recording" --record-every 0.5 --build-twin-on-land
```

Linux can use the same `screen:LEFT,TOP,WIDTH,HEIGHT` source if you do not use
the V4L2 device. Add `--crop x,y,w,h` to remove app overlays; crop values are
fractions when all are at most 1, otherwise pixels. The crop is applied before
recording.

## End a session and inspect outputs

Land the aircraft using DJI Fly. Then press Ctrl-C or use the dashboard STOP to
end the local live session. For a bounded bench run only, add
`--max-seconds 40`. Each sampled, post-crop frame is saved as a q90 JPEG under
`$recording/frames/`; `record.json` records the source, crop, start time, and
frame/drop counts. `flight.mp4` is also written when OpenCV's MP4 writer is
available.

With `--build-twin-on-land`, shutdown starts a detached build; it does not wait
for COLMAP or depth inference. Follow progress in
`$recording/twin_build.log` or the drone panel's **Twin build** status. The
dashboard polls local twin metadata every 10 seconds and reloads the twin and
depth clouds without a page refresh.

The build accepts an optional measured survey file:

```bash
--build-twin-on-land /path/to/measured-survey.json
```

Only real measured correspondences justify metric/site registration. Example
survey data remains example-only. If anchoring or reconstruction is insufficient,
the box twin and depth output stay clearly marked synthetic/assumed-pose.
Inspect `twin/out/twin.json`, `depth/out/depth.json`, and the recording log
before using the result as a site twin.

## Bench test without a phone

Loop an existing local warehouse clip into a 40-second input because file
capture ends at EOF:

```bash
mkdir -p "$HOME/sentinel-runs"
bench_clip="$HOME/sentinel-runs/warehouse-live-40s-$(date +%Y%m%d-%H%M%S).mp4"
ffmpeg -hide_banner -loglevel warning -stream_loop -1 -i twin/work/warehouse.mp4 \
  -t 40 -an -vf fps=10 -c:v libx264 -preset ultrafast -crf 25 \
  -pix_fmt yuv420p "$bench_clip"
recording="$HOME/sentinel-runs/live-test-$(date +%Y%m%d-%H%M%S)"
.venv/bin/python -m drone.run \
  --mode live --source "$bench_clip" --api http://localhost:8000 \
  --record "$recording" --record-every 0.5 --build-twin-on-land \
  --max-seconds 40
```

Inspect `record.json`, the numbered JPEGs, `twin_build.log`, and the published
dashboard assets. A stock clip without measured survey markers is expected to
use the non-metric fallback.
