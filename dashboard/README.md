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

The included 60-second fixture uses the fixed site geometry, a mock 20-product catalogue, simulated camera events and drone positions, mock Decisions answers, two tasks and a review candidate. No video or identities are included. Live Ask, review confirm/reject, STOP, and mission launch use the fixed REST contract. STOP requests safe landing; it does not claim physical acknowledgement. The live feed thumbnail accepts HTTP(S) image/MJPEG URLs (not RTSP).

`node scripts/fixtures.mjs` regenerates static site/products/demo data from `config/site.yaml`. It only writes inside dashboard. Vite reads optional `twin/out` assets from the sibling workstream, serves them in dev, and copies them at build time. Missing assets retain detailed metric box geometry. A server replay, when present, is copied as `server-demo.jsonl`. Deploy builds `/sentinel-spatial/`, adds a commit to `gh-pages` without rewriting its history, and enables branch-based Pages if absent. No workflow outside dashboard is modified.

Privacy: only short anonymous tracks are drawn; no face imagery is stored. AI/mission controls never enter the flight loop or bypass DJI safeguards.
