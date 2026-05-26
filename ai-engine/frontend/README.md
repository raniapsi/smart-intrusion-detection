# SOC Dashboard

React + TypeScript + Vite + Tailwind frontend for the converged IoT/AI SOC.
Consumes the FastAPI backend (step 7) over REST + WebSocket.

## Prerequisites

- Node.js >= 20 (Node 22 recommended)
- npm >= 10

## Install

```bash
cd frontend
npm install
```

## Run (development)

The dashboard expects the backend to be running on `localhost:8000`.

```bash
# Terminal 1 — backend
cd ..   # back to ai-engine root
python3 -m backend.cli serve \
    --topology dataset/topology/building_b1.yaml \
    --data-dir scoring_service/output \
    --port 8000

# Terminal 2 — frontend
cd frontend
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` and `/ws` to `:8000`.

## Build (production)

```bash
npm run build
# produces dist/ ; serve it from any static host or behind FastAPI
```

## Layout

- `src/api/` — typed wrapper around the FastAPI endpoints
- `src/hooks/` — `useApi` (polling) and `useEventStream` (WebSocket)
- `src/components/` — reusable UI pieces
- `src/pages/` — route targets: Dashboard, Alerts, Users
- `src/lib/format.ts` — small formatting helpers

## Pages

- `/` — main dashboard: building map, score card, alert feed, live ticker
- `/alerts` — full alert table with acknowledge filter
- `/users` — per-user profile + recent events