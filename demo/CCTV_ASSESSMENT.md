# ACTi CCTV assessment

## Bottom line

This is an assessment of the **ACTi CCTV example itself**, not the earlier Pexels shopper clip and not the hosted dashboard's simulated event recording. One non-looping file run produced **four look estimates and two pass-by events**. It detected **no pick-up or put-back events**; that does not prove nobody handled a product.

The source is [ACTi retail-store footage](https://www.youtube.com/watch?v=-1bRhYjw1qE). It is a recorded clip, not a live camera installation. Raw and derived footage is delivered separately, never committed here.

## What actually ran

- Code: integration commit `19236da`.
- Input: the ACTi MP4, one pass; 1810 source frames at 30fps, 905 frames processed at 15fps.
- Calibration: explicit `perception/calib/camera-1-cctv.json`, **not the Pexels calibration**.
- Perception options: `--mock --no-post`. Pose inference and geometric event calculations ran, but the Decisions integration was in mock mode. No `holding_product` or `reach_outcome` calls were triggered in this run. No server-acceptance or live camera-to-dashboard claim is made.
- The tracker issued 17 IDs, with at most five people detected simultaneously. Occlusion/fragmentation can issue several IDs for one person: **17 is not a unique-person count**.

| Source time | Algorithm output | Temporary track |
| ---: | --- | --- |
| 19.07 s | pass_by | t13 |
| 21.53 s | look estimate | t12 |
| 22.20 s | pass_by | t11 |
| 22.20 s | look estimate | t11 |
| 31.73 s | look estimate | t14 |
| 38.40 s | look estimate | t17 |

Source times come from the CCTV workstream's emission-time instrumentation. Event JSONL timestamps are processing wall-clock times, not source capture times. These are exact outputs of this run, not labelled accuracy measurements. Counts from separate looped RTSP tests must not be substituted.

## Real OpenAI assessment versus mock mode

Three separate **real `gpt-6-luna` `engagement_level` calls** assess unblurred person crops at 19.07, 22.20 and 31.73 seconds from this same recording. They are fresh calls on the final unblurred inputs, as requested by Zak, not reused results from the superseded masked crops. They are separate from the perception event run, not confirmations that its look/pass-by labels are correct.

Each inset shows the exact image submitted, its source time, returned score, confidence and policy. The supplied raw-response log records crop bounds/hashes and mock-disabled request metadata. A changed crop needs a new call: never reuse an old blurred-crop result as if it assessed the unblurred image.

The engagement **score is on a 0–3 scale, not a probability or accuracy**. Confidence and review/ignore policy are separate. A single image cannot verify walking, stopping, a product pick-up, a purchase or intent; model labels remain estimates.

## What this does not establish

- **Not eye tracking:** look events use a head/keypoint-direction heuristic.
- **Not a metric survey:** eight manually assumed floor correspondences fit with 0.69 px reprojection residual. A small fit residual does not validate distances, shelf locations or SKU identity.
- **Not product-behaviour ground truth:** no products were identified in these events. There is no validated pick-up, put-back, conversion or purchase count.
- **Not a live installation:** this was file input with posting disabled. The separate hosted replay's heatmap, Ask answer and counts are simulated and are not derived from this CCTV recording.
- **Not anonymised:** Zak explicitly requested no blur for this public CCTV example, including the fresh API crops. Temporary track IDs do not make visible faces anonymous. No face recognition or cross-visit identity is used, but this export is not privacy-safe customer footage; production redaction needs site-level validation.

Use the CCTV-only submission cut, not the superseded Pexels/RTSP snapshot montage. The broader presentation still shows separately labelled dashboard and drone simulations; they must not be presented as results generated from this clip.
