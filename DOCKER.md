# Docker setup

This Compose stack runs the live demo path:

```text
alert-sender (optional) -> middleware -> ai-backend -> dashboard
```

The alert sender is containerised as an optional service. It is not needed
for manual `curl` tests, but it is useful for demos because it sends random
scenarios to the middleware at a fixed interval.

## Start the app

Build and start the core services:

```bash
docker compose up --build
```

Open:

```text
http://localhost:5173
```

Services:

- AI backend: `http://localhost:8000`
- Middleware: `http://localhost:8010`
- Dashboard: `http://localhost:5173`

## Start with automatic alerts

```bash
docker compose --profile alerts up --build
```

By default, `alert-sender` posts one random scenario every 5 seconds with
1 second of jitter.

Override timing:

```bash
ALERT_INTERVAL=2 ALERT_JITTER=0 docker compose --profile alerts up --build
```

## Stop

```bash
docker compose down
```

## Notes

- The AI backend image expects these generated files to exist before build:
  - `ai-engine/features/output/baselines.json`
  - `ai-engine/models/trained/isoforest.joblib`
- The dashboard container runs Vite dev server. Its proxy targets Docker
  service names (`ai-backend`) instead of localhost.
- The middleware container forwards events to `http://ai-backend:8000`.
