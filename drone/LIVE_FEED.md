# Getting live Neo 2 video onto the Sentinel laptop

**Priority:** Zak flies with DJI Fly on Android, so use scrcpy over USB first.
RTMP is the fallback: Neo 2 support is unconfirmed. Sentinel consumes video only.

## A. PRIMARY: Android DJI Fly → scrcpy → Sentinel

One-time install/setup (do this before the five-minute run if packages need
downloading):

- **Linux:** `sudo apt install v4l2loopback-dkms scrcpy`; if `adb` is missing,
  also run `sudo apt install android-tools-adb`. Create the virtual camera with
  `sudo modprobe v4l2loopback video_nr=10 card_label=scrcpy exclusive_caps=1`.
- **macOS:** `brew install scrcpy`; if `adb` is missing, run
  `brew install --cask android-platform-tools`.
- On Android, open **Settings → About phone** and tap **Build number** seven
  times to enable Developer options. Enable **USB debugging**, connect the
  phone by USB, accept its prompt, and keep DJI Fly showing the live camera.
  Rotate the phone to landscape and leave auto-rotate enabled if the app needs it.
- The 5-minute timing below assumes packages are installed and Developer
  options have been enabled. First-time installs can take longer.

| Time | Action |
| --- | --- |
| 0:00–1:00 | Connect the unlocked phone by USB, accept the debugging prompt, and open DJI Fly's live camera view in landscape. |
| 1:00–2:00 | Run `adb devices`; confirm the phone appears as `device` (not `unauthorized`). |
| 2:00–3:00 | Run `bash drone/scripts/scrcpy_mirror.sh`. Linux uses `/dev/video10` when present; macOS opens a titled scrcpy window. |
| 3:00–5:00 | Linux with loopback: run Sentinel with `--source 10`. macOS or Linux without loopback: capture the scrcpy window with `--source screen:L,T,W,H`. Confirm the live image. |

The helper uses `--max-fps 30`, `--video-bit-rate 8M`, `--stay-awake`,
`--window-title SentinelNeo`, and `--no-audio`; on Linux it sends video to the
V4L2 sink without a playback window. Use `bash drone/scripts/scrcpy_mirror.sh
--device /dev/videoN` to select another loopback device, or append
`--crop W:H:X:Y` to crop at the Android-device level.

## B. Fallback: DJI Fly RTMP → local MediaMTX (support unconfirmed)

DJI publishes general DJI Fly livestream instructions, but the material located
for this task does not explicitly list the Neo 2 as a supported RTMP publisher.
The Neo 2 manual confirms live view in DJI Fly; it does not establish that this
view can be externally published. A third-party AirHub guide includes Neo 2 in
an O3/O4 air-unit and DJI Goggles 3 workflow, but that does not verify a
phone-only DJI Fly publisher for Zak's setup. Treat RTMP support as
**unconfirmed**. If DJI Fly has no
`Transmission → Live Streaming Platforms → RTMP` item, return to A.

**Five-minute check (Zak)**

| Time | Action |
| --- | --- |
| 0:00–1:00 | Connect phone and laptop to the same Wi-Fi; run `bash drone/scripts/rtmp_server.sh` on the laptop and note the printed LAN IP and RTMP URL. |
| 1:00–2:00 | In DJI Fly's camera view/settings, look for `Transmission → Live Streaming Platforms → RTMP`. If absent, stop and use A. |
| 2:00–3:00 | If available, enter `rtmp://<laptop-ip>:1935/live/neo` and start streaming. Only split server/key fields if DJI Fly accepts that format. |
| 3:00–5:00 | Run `python -m drone.run --mode live --source rtmp://localhost:1935/live/neo` and confirm video; if not connected, return to A. |

MediaMTX listens for RTMP on TCP 1935. A local synthetic stream can test the
pipeline without the drone: run `bash drone/scripts/test_pattern.sh` after
starting the server.

### B2. RTMP when the phone's Wi-Fi is taken by the drone (phone-only mode)

From W7's REA of DJI Fly: DJI Fly has built-in RTMP live streaming, but when the Neo 2 flies
**without the RC-N3**, the phone's Wi-Fi is connected to the drone, so the RTMP push leaves over
**cellular** and cannot reach `192.168.x.x` on the laptop. Options, fastest first:

1. **Use scrcpy instead (A).** USB mirroring works in both modes and needs no network. Recommended.
2. **Fly with the RC-N3**: the phone talks to the controller over USB, so its Wi-Fi is free to join
   the laptop's LAN; then B works as written with `rtmp://<laptop-ip>:1935/live/neo`.
3. **Public TCP tunnel to the laptop's MediaMTX** (ngrok; needs a free account, TCP endpoints may ask
   for card verification):
   ```bash
   bash drone/scripts/rtmp_server.sh            # terminal 1
   ngrok tcp 1935                               # terminal 2 -> "Forwarding tcp://0.tcp.eu.ngrok.io:14321"
   # DJI Fly RTMP URL:  rtmp://0.tcp.eu.ngrok.io:14321/live/neo
   python -m drone.run --mode live --source rtmp://localhost:1935/live/neo
   ```
   A `cloudflared` quick tunnel does **not** work here: Cloudflare TCP tunnels need `cloudflared` on
   the *client* (the phone) too, and quick tunnels are HTTP only.
4. **Cloud relay**: run MediaMTX on any public VM (e.g. `docker run --rm -p 1935:1935
   bluenviron/mediamtx`), point DJI Fly at `rtmp://<vm-ip>:1935/live/neo`, and pull it on the laptop
   with `--source rtmp://<vm-ip>:1935/live/neo`. Adds a cellular round trip of latency.

Measured locally (test pattern -> MediaMTX -> `LiveFeedDriver`): first frame after ~6 s (OpenCV
stream probing), then a steady 10 fps.

## C. Crop the DJI Fly controls out of the image

`LiveFeedDriver` and `preview.py --crop` accept `x,y,w,h`. If all four values
are at most 1, they are frame fractions (for example
`0.1,0.08,0.8,0.84`); otherwise they are integer source-pixel coordinates and
dimensions (for example `120,180,1280,720`). Values are applied to frames
before they are returned.

**One-minute crop tuning:** show the scrcpy window, find its screen rectangle,
then run:

```bash
python drone/scripts/preview.py \
  --source screen:L,T,W,H \
  --crop 0.1,0.08,0.8,0.84 \
  --snapshot drone/out/neo_crop.jpg
```

For the Linux V4L2 route, replace the source with `10`. Inspect the saved
snapshot, adjust the four crop values, and rerun. The scrcpy-level crop uses a
different order: `--crop W:H:X:Y` in Android device pixels; pass it to the
helper as `bash drone/scripts/scrcpy_mirror.sh --crop W:H:X:Y`.

## D. iPhone mirror → laptop capture

| Time | Action |
| --- | --- |
| 0:00–1:00 | Open the Neo 2 live view in DJI Fly on the iPhone; connect the phone to the Mac. |
| 1:00–3:00 | In QuickTime Player choose `File → New Movie Recording` and select iPhone as the camera source. Alternatively use a previously configured trusted AirPlay receiver or OBS virtual camera. |
| 3:00–4:00 | Capture the visible mirror with `--source screen:LEFT,TOP,WIDTH,HEIGHT`, or run `python drone/scripts/list_sources.py` and choose its camera index as `--source N`. |
| 4:00–5:00 | Confirm the live DJI Fly image (not a black/permission screen) is visible in Sentinel. |

Exact QuickTime/AirPlay and OBS device indices depend on macOS version and
installed virtual-camera drivers.

## E. Recorded MP4 fallback

| Time | Action |
| --- | --- |
| 0:00–2:00 | Use DJI Fly to transfer a recorded clip, or copy an existing MP4 to the laptop. |
| 2:00–3:00 | Run `python -m drone.run --mode live --source /path/to/clip.mp4`. |
| 3:00–5:00 | Confirm the image; capture starts from the beginning and ends at end-of-file. |

## Troubleshooting

- **No RTMP menu / connection rejected:** Neo 2 RTMP support is unconfirmed;
  use Android scrcpy or iPhone mirroring.
- **No frames:** check the source with
  `python drone/scripts/preview.py --source SOURCE --crop CROP --snapshot drone/out/live_test.jpg`.
  For a camera index, run `python drone/scripts/list_sources.py`.
- **RTMP cannot connect:** ensure phone and laptop share a reachable network,
  permit inbound TCP 1935 in the laptop firewall, and use the LAN IP printed by
  `rtmp_server.sh` (not `localhost`) in DJI Fly. Guest Wi-Fi/client isolation
  can block phone-to-laptop traffic.
- **High delay:** reduce DJI Fly bitrate/resolution if those controls are
  offered, avoid Wi-Fi congestion, close duplicate viewers, and prefer scrcpy's
  low-buffer mirror. Network RTMP buffering varies.
- **Black or misplaced screen capture:** keep the DJI Fly camera view in front,
  update the screen rectangle after moving/resizing scrcpy, and ensure screen
  capture permissions are enabled.
- **The file is exhausted:** use a new MP4 or restart the driver; local files
  are not looped automatically.

> **Guardrails:** video only; no firmware modifications; DJI safety features
> stay enabled; a human pilots the aircraft. Any future control backend must be
> wrapped by Sentinel's safety supervisor and must never bypass DJI safety.

## Sources

- [DJI Neo 2 User Manual (v1.0)](https://downloads.ctfassets.net/wl6a3py7hwd8/3xw8PBU2FsOYbIZxLOcRjF/f212fd987c56d5622b42aed24798bdeb/DJI_Neo_2_User_Manual_v1.0_en.pdf)
- [DJI Help Center: DJI Fly App Livestream Operation Guides search](https://support.dji.com/help/search?defaultOpened=&folderIdList=0&keyword=DJI+Fly&lang=en&limit=9&page=1&re=US&spaceId=34&trackId=aced5ce2-f526-4c59-83fd-34e19868cdcd)
- [DJI Neo 2 FAQ](https://www.dji.com/tw/neo-2/faq)
- [AirHub: RTMP for Avata 2 / FPV (goggles setup)](https://www.airhub.app/resources/news/live-streaming-dji-avata-2-fpv-rtmp-airhub)
- [MediaMTX: publish with RTMP](https://mediamtx.org/docs/publish/rtmp)
- [MediaMTX configuration reference](https://mediamtx.org/docs/references/configuration-file)
- [scrcpy: Video4Linux sink](https://github.com/Genymobile/scrcpy/blob/HEAD/doc/v4l2.md)
- [scrcpy: no-playback option](https://github.com/Genymobile/scrcpy/blob/HEAD/doc/video.md)
