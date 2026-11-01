# Sentinel — live pitch

**3 minutes.** Open [the hosted replay](https://zakee47.github.io/sentinel-spatial/?replay=demo.jsonl) before presenting. It is a read-only product UI over a **simulated event recording**, not a live warehouse connection. Pause near the end; keep the video ready if Wi-Fi fails. The labels below describe the evidence on screen, not production readiness.

## 00:00–00:20 · The missing signal — LIVE PRODUCT

“Your till tells you what sold. Your warehouse system tells you what should be on the shelf. Neither tells you where shoppers looked, what they picked up and put back, or which pick face is empty right now. Sentinel connects those missing observations to a shared map of the floor.”

**Show:** dashboard overview. Say “recorded demo” before touching replay.

## 00:20–01:00 · Walk the product — LIVE PRODUCT / SIMULATION DATA

“This is the working dashboard, playing a recorded simulation. Every shelf and bay has a place in metres. Scrub the timeline: attention builds on the shelf. Switch to Top and back to 3D. Ask which shelf underperformed: Shelf A2 drew 37 looks, but only two products were kept and 21 were put back. Those are demo counts, not a sales experiment. The answer here is a deterministic replay summary, not a live model answer. Uncertain events go to this review queue; read-only replay cannot approve them.”

**Actions:** scrub early → late; Top → 3D; Ask suggestion; review queue. Keep versus look is a proxy, **not a confirmed purchase**. If depth is disabled, say “No depth asset is loaded in this hosted replay”; do not pretend to enable it.

## 01:00–01:35 · How it works — REAL CCTV / MOCK EVENT MODE / REAL CROP CALLS

“This is actual CCTV footage, not our earlier shopper example. Local pose tracking produced four look estimates and two pass-by events; it detected no pick-up or put-back. Three separate, real OpenAI Decisions calls assess face-masked crops from this same recording. Their engagement scores, confidence and review policies are model estimates—not verified purchases or proof of those event labels. The event run itself used mock mode. Devin is the mission-manager integration: plan inspections and raise staff tasks, never fly the aircraft. Its demonstrated run was simulated; a real API launch was not verified.”

**Show:** ACTi tracking annotation → actual crop/result insets → drone panel. This is one non-looping file run with ACTi-specific manual calibration, not a live RTSP camera. Do not substitute the earlier Pexels eight-event result, old twelve-event RTSP result, or another run's counts. The manual 0.69 px fit residual is not measured metric/SKU accuracy. The hosted dashboard remains a separate simulated replay, not this clip's event store.

## 01:35–02:20 · The drone and REA — SIMULATION / LIVE PRODUCT RESEARCH

“The drone is how we reach the places a fixed camera misses. This patrol is explicitly a simulation: four bays, an empty B-02 pick face, a misplaced B-03 carton, and two staff tasks. We used REA to inspect the official DJI Fly app. The result mattered: Neo 2 has no supported public control SDK. We did not wire into its private virtual-stick command or bypass DJI safety. A human pilot, or DJI’s own flight modes, flies; DJI Fly RTMP or an Android screen mirror supplies video. Our local supervisor is exercised in simulation, outside AI and network calls. The depth example is learned from video: pseudo-LiDAR, not measured LiDAR, and not exported from the drone’s sensors.”

**Show:** patrol GIF; expanded REA card; learned-depth cloud. No connected aircraft or live phone mirroring was verified. The supplied cloud uses approximate calibration and assumed poses; independent frames are **not** a fused metric survey. The metric rack/twin preview is procedural geometry.

## 02:20–02:40 · Privacy — LIVE PRODUCT DESIGN

“The processing pipeline is designed to keep video local. No face recognition, no customer identity across visits: just short-lived tracks and events. Only small, face-blurred evidence crops go to the model. These public demo clips are presentation material, not customer footage uploaded by the product.”

**Show:** privacy card. The CCTV assessment export masks face/head regions; this is a demo redaction, not a certified anonymisation guarantee. Real API crops must match the masked images actually sent, not earlier whole-crop-blurred inputs.

## 02:40–03:00 · What comes next — LIVE PRODUCT ROADMAP

“Next: calibrate a real site, validate decisions against labelled footage, and connect the human-piloted feed. A supported aircraft SDK is a separate step for real autonomous flight. Today, Sentinel makes the floor visible: observation, judgement, and a task somebody can act on.”

**Close:** overview; avoid launching disabled missions in replay. Do not promise current CRM, POS integration, phone notifications, physical STOP acknowledgement or measured inventory accuracy.

## 60-second fallback

**00:00–00:12 · LIVE PRODUCT** — “Your till sees sales; your warehouse system sees expected stock. Neither sees a shopper putting a product back or an empty pick face. Sentinel puts those observations on one map.”

**00:12–00:28 · LIVE PRODUCT / SIMULATION DATA** — “This working dashboard replays simulated events: shelf attention, a kept-versus-look funnel, and a review queue. Ask Sentinel gives a local summary: 37 looks, two kept, 21 put back on A2. That is demo evidence, not confirmed sales.”

**00:28–00:43 · REAL CCTV / MIXED REAL + MOCK** — “This ACTi recording produced four look estimates and two pass-by events in mock event mode. Three separate real Decisions calls assess crops from the same footage. Drone flight and the demonstrated mission-manager run remain simulations.”

**00:43–01:00 · SIMULATION / LIVE PRODUCT RESEARCH** — “REA found no supported Neo 2 control SDK, so humans or DJI fly; we ingest video, not flight commands. Depth is estimated, not LiDAR. No identities across visits; local video and small blurred crops. Next is calibrated, real-site validation.”

## Judge Q&A crib

| Question | Short, defensible answer |
| --- | --- |
| Why Decisions API rather than a chat model? | We need bounded choices, probabilities/confidences and scores that map to explicit auto/review/ignore thresholds, rather than free-form prose. The same crop can answer a versioned question set; logs record policy, usage and latency. It does not remove the need for calibration or ground truth. |
| What did the real API actually do? | Three real `gpt-6-luna` `engagement_level` calls assessed masked crops from the ACTi footage. We show the exact crop, source timestamp, engagement score (0–3), confidence and routing policy. The raw responses are separate from the mock event run. Single frames do not verify walking/stopping or purchases. Earlier synthetic bay examples exist in PR #3 but are not this submission's evidence. |
| What does a decision cost? | We have token usage, not a verified dollar bill or published rate here. A sample bay call used 3,061 input tokens, 2,036 cached; severity used 2,325, 2,141 cached. Multiply uncached/cached input and output tokens by the applicable account rates. Include retries, multiple questions and crop frequency. Do not invent cents per decision; measure billed usage before quoting unit economics. |
| Can Devin fly into a person? | Devin is not in the flight loop. The Neo 2 live driver is video-only and rejects flight methods. Human/DJI controls the aircraft. Simulated flight has local geofence, speed/altitude, battery, lost-fix/link and person-proximity tests; that is not a hardware safety certification. |
| Is the cloud LiDAR? | No. Depth Anything V2 estimates axial depth from video, then RGB points are back-projected with approximate intrinsics/pose. No Neo 2 raw depth export, no validated metric scan, and no multi-frame fusion without matched poses. |
| What is actually real versus simulated? | Real: browser UI, ACTi source-video decoding/pose inference, three separately recorded real Decisions crop responses, RTSP plumbing, CPU learned-depth inference and REA inspection. Mock/simulated: perception event mode, hosted event replay, catalogue/till data, metric twin geometry, drone flight and demonstrated Devin mission run. No real aircraft integration demonstrated. |
| Is “look” eye tracking or “kept” a sale? | Neither. Look is an approximate head-direction/keypoint proxy intersecting a shelf zone; this clip has manually estimated calibration and hip floor-position fallback. Kept is a reach/outcome estimate, not payment confirmation. |
| Does the CCTV test prove SKU accuracy? | No. The replacement uses ACTi-specific manual calibration, but its assumed coordinates and low reprojection residual are not surveyed geometry or product ground truth. Its actual output was four look estimates and two pass-bys, no pick-ups or put-backs. Separate real crop calls do not validate SKU attribution or the event labels. |
| Did REA unlock private DJI controls? | No. It identified a private control architecture and official video path. We did not invoke private controls, modify firmware or change DJI safety features. No aircraft was connected during that investigation. |
| Why not just use a camera dashboard? | The proposed value is a common spatial context: combine attention, inventory observations, inspection coverage and actionable tasks at the same shelf/bay. Measured business ROI remains future work. |

## Evidence references

- [#1 — Devin integration; demonstrated mock, real key rejected](https://github.com/Zakee47/sentinel-spatial/pull/1)
- [#2 — dashboard replay and read-only controls](https://github.com/Zakee47/sentinel-spatial/pull/2)
- [#3 — exact real Decisions results on synthetic images](https://github.com/Zakee47/sentinel-spatial/pull/3)
- [#4 — perception and approximation limits](https://github.com/Zakee47/sentinel-spatial/pull/4)
- [#5 — canonical simulated replay, two tasks](https://github.com/Zakee47/sentinel-spatial/pull/5)
- [#6 — procedural metric twin, not a surveyed scan](https://github.com/Zakee47/sentinel-spatial/pull/6)
- [#7 — REA / DJI feasibility verdict](https://github.com/Zakee47/sentinel-spatial/pull/7)
- [#8 — simulated patrol and video-only live driver](https://github.com/Zakee47/sentinel-spatial/pull/8)
- [#9 — learned video depth, not fused LiDAR](https://github.com/Zakee47/sentinel-spatial/pull/9)
- [#10 — 12 events from looped CCTV RTSP; reused calibration](https://github.com/Zakee47/sentinel-spatial/pull/10)
- [ACTi-specific manual calibration used by the replacement](https://github.com/Zakee47/sentinel-spatial/blob/19236da/perception/calib/camera-1-cctv.json)

The ACTi replacement's exact event counts are from its delivered `events.jsonl` and `summary.json`, not the older transport-test counts. These are recorded prototype results, not an accuracy benchmark.
