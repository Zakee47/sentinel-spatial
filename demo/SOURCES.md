# Demo sources and provenance

Only `demo/` is changed by this pack. Public footage is shown as presentation evidence, never as a live customer installation. All inputs, generated media and raw screen captures are ignored by git. In particular **do not commit the ACTi source video, snapshot, or rendered derivatives**. Final videos are delivered as session attachments, not repository blobs.

## Rebuilding

Requirements: Python 3.11+, Pillow (`python3 -m pip install Pillow==11.3.0`), FFmpeg with libx264, and DejaVu Sans/Mono fonts (standard Ubuntu package `fonts-dejavu-core`). No API key, app dependencies or GPU are required. The script never fetches footage or contacts an API.

Put these source files in `demo/inputs/`, or pass another folder with `--inputs /absolute/path`:

| Required basename | Source / honest description |
| --- | --- |
| `dashboard.mp4` | This session's real-time hosted replay capture, 1400×1050; browser content 1400×899, DPR1. Source is `demo/raw/w11-hosted-walkthrough-realtime.mp4`, also supplied separately as an attachment. Do not use the recording tool's accelerated edit: storyboard timestamps refer to real time. |
| `annotated.mp4` | Supplied 21.8-second perception annotation, 1280×720. [Pexels 5104001](https://www.pexels.com/video/customer-picking-food-items-from-a-supermarket-5104001/), [Pexels licence](https://www.pexels.com/license/). Real pose pipeline, manual approximate calibration, mocked Decisions. |
| `patrol.gif` | Supplied 7-second four-bay simulator output; looped and explicitly labelled SIMULATION. No physical flight. |
| `snapshot.jpg` | Supplied RTSP snapshot from [ACTi retail CCTV clip](https://www.youtube.com/watch?v=-1bRhYjw1qE). Standard YouTube licence; permission in this demo brief is to show it in the presentation, not to commit raw footage or claim an open-source licence. This pack does not download the YouTube video. |
| `preview.png` | Supplied procedural metric twin preview (214,658 points). No captured survey. |
| `cloud.png` | Supplied actual learned-depth inference evidence from Tiger Lily / [Pexels warehouse clip 4294436](https://www.pexels.com/video/4294436/). Depth Anything V2 Metric Indoor Small; 20,688 rendered RGB points. Approximate calibration, assumed pose, independent frames, not fused and not measured LiDAR. See PR #9 for model licensing/usage caveats. |

```sh
bash demo/build_video.sh --inputs /path/to/inputs
# Cards-only preview:
bash demo/build_video.sh --cards-only
# Submission form: <=90 seconds, working product only, no slides:
bash demo/build_video.sh --submission-only --inputs /path/to/inputs
```

Output: `demo/output/sentinel-demo.mp4` and an identical explicitly named `sentinel-demo-no-vo.mp4` (silent, caption-led by design), plus three standalone clips. The same 1920×1080 H.264 settings apply to all. The renderer checks main duration 120–150 seconds, each clip 10–20 seconds, dimensions, codec and ≤60 MB per file. `validation.json` contains actual probe results. `storyboard.json` is the edit decision list and all card text; `render.py` is the Pillow card source.

The separate `--submission-only` export creates `sentinel-submission-88s.mp4`: 88 seconds of the actual hosted UI, at real time, with browser chrome removed and persistent replay-disclosure captions. No title cards, slides, source-footage montage or simulated replacement UI is inserted. It shows timeline scrubbing, 3D/Top, unavailable depth, Ask, review queue and the drone/REA panel. `submission-validation.json` records the probe result. Use this shorter cut for the submission form, not the 135-second presentation video. Upload it to YouTube (unlisted), Loom, or Drive with anyone-with-the-link viewing, and verify signed-out access; Devin attachment links are not public judge links.

## Real hosted capture

Recorded 1 November 2026 at [the hosted dashboard](https://zakee47.github.io/sentinel-spatial/?replay=demo.jsonl). Source: 95.67 seconds at 1400 CSS px / DPR1, checked in an actual screenshot before capture. Screen recording contains browser chrome; the edit crops it away without scaling the browser viewport. Native UI remains real; no replacement data or generated UI overlays are inserted inside the dashboard.

Captured: late twin/heatmap, actual timeline drag early then late, Top→3D, unavailable depth tooltip, Ask suggestion/summary, 119-item review queue, drone SIM panel and expanded REA card. Hosted depth could **not** be toggled on because no asset was present; the video uses the separately credited depth evidence instead. Writes and drone actions stay disabled in read-only replay. Ask explicitly labels its answer a deterministic summary, not an API answer.

## Fact-checking

The workstream PRs #1–#10 are linked in [SCRIPT.md](SCRIPT.md). All quoted model timings/confidences come from PR #3's recorded real calls on **synthetic** inputs. The hosted replay is from PR #5's simulator; it is not the annotated perception clip's event recording. The eight-event perception result and twelve-event CCTV transport result are separate demonstrations, not one calibrated deployment. The separate footage clips must not be presented as the exact underlying source of the hosted heatmap.

The W8 mission-agent test used a mocked launch; the real key was rejected. No successful real Devin API session or real aircraft/phone connection is claimed. Neo 2 flight stays human-/DJI-controlled. The simulated supervisor is not hardware-certified.
