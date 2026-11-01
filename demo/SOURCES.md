# Demo sources and provenance

Only `demo/` is changed by this pack. Public footage is shown as presentation evidence, never as a live customer installation. All inputs, generated media and raw screen captures are ignored by git. In particular **do not commit the ACTi source video, snapshot, or rendered derivatives**. Final videos are delivered as session attachments, not repository blobs.

## Rebuilding

Requirements: Python 3.11+, Pillow (`python3 -m pip install Pillow==11.3.0`), FFmpeg with libx264, and DejaVu Sans/Mono fonts (standard Ubuntu package `fonts-dejavu-core`). No API key, app dependencies or GPU are required. The script never fetches footage or contacts an API.

Put these source files in `demo/inputs/`, or pass another folder with `--inputs /absolute/path`:

| Required basename | Source / honest description |
| --- | --- |
| `dashboard.mp4` | This session's real-time hosted replay capture, 1400×1050; browser content 1400×899, DPR1. Source is `demo/raw/w11-hosted-walkthrough-realtime.mp4`, also supplied separately as an attachment. Do not use the recording tool's accelerated edit: storyboard timestamps refer to real time. |
| `cctv-assessed.mp4` | Actual ACTi CCTV assessment export from the CCTV workstream: pose/track overlays and three freshly recorded real Decisions crop calls. Zak directly requested "no blur please": use the unblurred video and unblurred API crops, not superseded masked cuts/results. No anonymisation is claimed. Event-run mock status and calibration caveats remain visible. |
| `patrol.gif` | Supplied 7-second four-bay simulator output; looped and explicitly labelled SIMULATION. No physical flight. |
| `preview.png` | Supplied procedural metric twin preview (214,658 points). No captured survey. |
| `cloud.png` | Supplied actual learned-depth inference evidence from Tiger Lily / [Pexels warehouse clip 4294436](https://www.pexels.com/video/4294436/). Depth Anything V2 Metric Indoor Small; 20,688 rendered RGB points. Approximate calibration, assumed pose, independent frames, not fused and not measured LiDAR. See PR #9 for model licensing/usage caveats. |

CCTV source: [ACTi retail-store footage](https://www.youtube.com/watch?v=-1bRhYjw1qE), standard YouTube licence. The brief permits presentation use, not committing footage or claiming an open-source licence. This renderer never downloads source footage. The earlier Pexels shopper annotation and RTSP snapshot are no longer used by the revised storyboard.

```sh
bash demo/build_video.sh --inputs /path/to/inputs
# Cards-only preview:
bash demo/build_video.sh --cards-only
# Submission form: <=90 seconds, working product only, no slides:
bash demo/build_video.sh --submission-only --inputs /path/to/inputs
# Preferred replacement after Zak's CCTV-only assessment request:
bash demo/build_video.sh --cctv-only --inputs /path/to/cctv-inputs
```

Output: `demo/output/sentinel-demo.mp4` and an identical explicitly named `sentinel-demo-no-vo.mp4` (silent, caption-led by design), plus three standalone clips. The same 1920×1080 H.264 settings apply to all. The renderer checks main duration 120–150 seconds, each clip 10–20 seconds, dimensions, codec and ≤60 MB per file. `validation.json` contains actual probe results. `storyboard.json` is the edit decision list and all card text; `render.py` is the Pillow card source.

The earlier `--submission-only` export creates `sentinel-submission-88s.mp4`: 88 seconds of the actual hosted UI, at real time, with browser chrome removed and persistent replay-disclosure captions. It shows timeline scrubbing, 3D/Top, unavailable depth, Ask, review queue and the drone/REA panel. `submission-validation.json` records its probe result. **Zak's later CCTV-only request supersedes this as the submission choice.** Use the CCTV-only export below instead. Upload the chosen video to YouTube (unlisted), Loom, or Drive with anyone-with-the-link viewing, and verify signed-out access; Devin attachment links are not public judge links.

## CCTV-only replacement

Zak requested the ACTi CCTV example and an assessment of that same footage, **not** the earlier Pexels shopper example or simulated replay counts. The CCTV-only export takes two inputs:

- `cctv-assessed.mp4`: actual ACTi CCTV assessment output, with source-frame and model-result provenance retained. It must use the ACTi-specific `perception/calib/camera-1-cctv.json` from the integration branch, not the original Pexels calibration. Its eight manually assumed pixel-to-twin pairs have a 0.69 px fit residual; this is not surveyed metric accuracy or validated SKU attribution.
- `cctv-captions.txt`: one or two short disclosure lines (at most 140 characters each), derived from the delivered run's real-versus-mock status. Never relabel mock event decisions as real API judgments.

`--cctv-only` exports `sentinel-submission-cctv.mp4`: at most 88 seconds of that same input, real time, with persistent source/disclosure captions and **no inserted slides, earlier shopper example or simulated dashboard**. The renderer does not run perception or call an API; preserve the assessment report and logs with the input artifacts. The actual probe results are written to `cctv-validation.json`. The delivered cut is **60.30 seconds, 1920×1080 H.264, 19.22 MB**, with faststart; its full FFmpeg decode passed. It supersedes the earlier 88-second dashboard submission. The footer records the three real calls' policies as #1 AUTO / #2 AUTO / #3 REVIEW.

### Actual ACTi event run

The CCTV workstream ran integration commit `19236da` with the ACTi file, explicit `camera-1-cctv.json`, `--mock --no-post`, one non-looping pass. It processed 905 frames from the 1810-frame, 30fps source (15fps processing). Exact event output: **4 look, 2 pass_by, 0 pick_up, 0 put_back**. The 17 issued tracker IDs are not 17 unique people; maximum simultaneous detections was 5. These counts differ from a separate RTSP test and must not be substituted with that test's numbers.

The real `gpt-6-luna` crop calls are separate from the mock-mode event run. Their score is an engagement-scale estimate (0–3), not a probability or accuracy; confidence and policy are separate fields. Single-frame crop judgments do not verify walking/stopping, purchases, SKU identity or the heuristic event labels. Keep the exact source timestamps, crop hashes and raw responses in the assessment report/logs. Final video and API crops are unblurred at the owner's explicit request; this is public source material, not anonymised customer footage. Do not reuse earlier blurred-crop API outputs on the new unblurred images.

## Real hosted capture

Recorded 1 November 2026 at [the hosted dashboard](https://zakee47.github.io/sentinel-spatial/?replay=demo.jsonl). Source: 95.67 seconds at 1400 CSS px / DPR1, checked in an actual screenshot before capture. Screen recording contains browser chrome; the edit crops it away without scaling the browser viewport. Native UI remains real; no replacement data or generated UI overlays are inserted inside the dashboard.

Captured: late twin/heatmap, actual timeline drag early then late, Top→3D, unavailable depth tooltip, Ask suggestion/summary, 119-item review queue, drone SIM panel and expanded REA card. Hosted depth could **not** be toggled on because no asset was present; the video uses the separately credited depth evidence instead. Writes and drone actions stay disabled in read-only replay. Ask explicitly labels its answer a deterministic summary, not an API answer.

## Fact-checking

The workstream PRs #1–#10 are linked in [SCRIPT.md](SCRIPT.md). The revised CCTV section uses actual ACTi input and separately recorded real crop calls, not PR #3's earlier synthetic bay examples or the Pexels shopper results. The historical eight-event Pexels result and twelve-event RTSP transport result are not the current six-event ACTi run. The hosted replay is still from PR #5's simulator, **not** the actual CCTV event recording; do not imply that its heatmap or Ask counts are derived from this clip.

The W8 mission-agent test used a mocked launch; the real key was rejected. No successful real Devin API session or real aircraft/phone connection is claimed. Neo 2 flight stays human-/DJI-controlled. The simulated supervisor is not hardware-certified.
