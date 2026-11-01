# Sentinel

Spatial AI for warehouses and retail. Ordinary cameras and a drone feed a shared 3D digital twin; the **OpenAI Decisions API** makes small judgement calls on image crops; a **Devin** mission agent turns findings into drone patrols and staff tasks.

- Product brief: [docs/BRIEF.md](docs/BRIEF.md)
- Hackathon plan and workstreams: [docs/PLAN.md](docs/PLAN.md)
- Contracts (API, events, WebSocket, replay): [contracts/API.md](contracts/API.md)
- Site config (geometry, thresholds): [config/site.yaml](config/site.yaml) · DB schema: [db/schema.sql](db/schema.sql)

Setup: copy `.env.example` to `.env` and fill in `OPENAI_API_KEY` (and `DEVIN_API_KEY` for the mission agent). Each folder has its own README with run instructions.
