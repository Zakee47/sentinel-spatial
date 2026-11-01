# Sentinel dashboard

Vite + vanilla TypeScript + three.js. IBM Plex fonts only; beige/ink/blue design tokens from the supplied Cognition pack.

```sh
cd dashboard
npm ci
npm run dev
# http://localhost:5173/?replay=demo.jsonl
npm run lint && npm run typecheck && npm test
npm run build
GH_PAT=... ./deploy-pages.sh
```

Live mode proxies `/api` and `/ws` to localhost:8000. For a remote backend use `?api=https://your-api.example` or build with `VITE_API_URL`; backend CORS must allow the dashboard. Without a backend, a clearly labelled **offline local simulation** runs and flight/mission/review writes are disabled. Replay (`?replay=demo.jsonl` or an absolute JSONL URL) never connects a WebSocket or writes to the API. Play, pause, seek, restart, and 0.5–4× speed are supported. Replay Ask is explicitly a deterministic local summary, not an OpenAI answer.

The fallback 60-second fixture uses the fixed site geometry, a mock 20-product catalogue, simulated camera events and drone positions, mock Decisions answers, two tasks and a review candidate. No video or identities are included. Live Ask, review confirm/reject, STOP, and mission launch use the fixed REST contract. STOP requests safe landing; it does not claim physical acknowledgement. The live feed thumbnail accepts HTTP(S) image/MJPEG URLs (not RTSP). `mode`/`driver` label simulated and human-piloted feeds separately; an unspecified live driver is labelled LIVE, not autonomous.

`node scripts/fixtures.mjs` regenerates fallback static site/products/demo data from `config/site.yaml`. `node scripts/sync-assets.mjs` (also called automatically when Vite starts/builds) replaces the bundled trio with W1's `replay/demo.jsonl`, `site.json`, and `products.json` only when all three exist, reading the local checkout or fetched `origin/devin/1793549929-server`. It also copies `docs/rea/findings.json` from the checkout or fetched `origin/devin/1793550562-rea-drone` into `public/rea/` for the REA integration card. Run `git fetch origin` before building to refresh those branches. All writes stay inside dashboard. GitHub Pages defaults to the bundled replay; `?live=1&api=https://your-api.example` explicitly connects live.

Vite reads optional `twin/out` assets from the sibling workstream, serves them in dev, and copies them at build time. Missing assets retain detailed metric box geometry. An independent, initially-off depth toggle loads `depth/out/depth_points.bin` when present (Float32 xyzrgb, z-up metres, RGB 0–1 or 0–255); unavailable or invalid depth keeps the toggle disabled. Depth is labelled an estimate, not DJI LiDAR or flight-control data. Build copies available depth assets into `dist/depth/out/`.

The CCTV card probes `http://localhost:8090/cameras/camera-1/mjpeg` using an image (no cross-origin fetch required). It is hidden unless the feed loads, hides on failure, and retries every 30 seconds. On a hosted page, localhost is the viewer's machine; the browser may require local-network permission or block HTTP content. It never invents a feed or uploads video. Deploy builds `/sentinel-spatial/`, adds a commit to `gh-pages` without rewriting its history, and enables branch-based Pages if absent. No workflow outside dashboard is modified.

Privacy: only short anonymous tracks are drawn; no face imagery is stored. AI/mission controls never enter the flight loop or bypass DJI safeguards.
