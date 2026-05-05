# Smart Intrusion Detection — Middleware, Streaming, AI Engine & Dashboard

> **Scope of this repository.** This repo implements the **layers 5 through 8**
> of the team architecture document (`README` produced by the full team):
> the middleware that ingests normalised events, the Kafka streaming bus,
> the AI scoring engine, and the SOC dashboard. The PQC/TLS security layer
> (layer 4) and the field simulator (layers 1–3) are out of scope here —
> they live in sibling repositories owned by the security and simulation
> sub-teams.
>
> **Authors of this scope:** Ilyes Belkhir, Sam Bouchet, Alban Robert.

---

## Table of Contents

1. [Position in the global architecture](#1-position-in-the-global-architecture)
2. [Components delivered](#2-components-delivered)
3. [End-to-end data flow](#3-end-to-end-data-flow)
4. [Kafka integration](#4-kafka-integration)
5. [HTTP fallback path](#5-http-fallback-path)
6. [Running the stack](#6-running-the-stack)
7. [API surface](#7-api-surface)
8. [Repository layout](#8-repository-layout)
9. [Configuration reference](#9-configuration-reference)
10. [End-to-end verification](#10-end-to-end-verification)

---

## 1. Position in the global architecture

The team architecture document defines 8 layers. This repository owns the
middle and upper part of the stack:

```
┌──────────────────────────────────────────────────────────────┐
│ [8] SOC DASHBOARD — React + Vite + WebSocket            ✓    │
│                                                              │
│ [7] AI ENGINE — Isolation Forest + rules + fusion       ✓    │
│                                                              │
│ [6] STREAMING — Apache Kafka (events.raw, .enriched, …) ✓    │
│                                                              │
│ [5] MIDDLEWARE — FastAPI ingest + normalisation         ✓    │
│ ──────────────────────────────────────────────────────────── │
│ [4] SECURITY — PQC TLS / hybrid signatures              ✗    │
│ [3] GATEWAY — software MQTT bridge                      ✗    │
│ [2] PROTOCOLS — MQTT / HTTP                             ✗    │
│ [1] IoT FIELD — Python multi-agent simulator            ✗    │
└──────────────────────────────────────────────────────────────┘
```

The middleware exposes a plain HTTP `/api/events` endpoint, which is the
contract used by both the simulator team and a future Node-RED integration.
The exact JSON shape on `events.raw` (the **Unified Event Schema**) follows
section 5.3 of the team architecture document.

---

## 2. Components delivered

### 2.1 `middleware/` — FastAPI ingest service

A small FastAPI app that:
- accepts normalised events on `POST /api/events`
- publishes each event on the Kafka topic `events.raw` (canonical path)
- additionally HTTP-forwards to the AI engine (`POST /api/ingest/events`)
  when Kafka is unavailable (fallback)
- exposes `/api/alerts` and `/api/health` for the dashboard / smoke tests
- ships an automatic alert generator (`scripts/auto_alerts.py`) used in the
  optional `alerts` Compose profile

Key files:

| File | Purpose |
|---|---|
| [middleware/app/main.py](middleware/app/main.py) | FastAPI factory, `lifespan` that pre-warms the Kafka producer at startup and flushes it at shutdown |
| [middleware/app/api/routes.py](middleware/app/api/routes.py) | REST routes, `BackgroundTasks`-based forwarding |
| [middleware/app/services/kafka_producer.py](middleware/app/services/kafka_producer.py) | Thread-safe `KafkaPublisher` (lazy init, delivery callbacks, graceful close) |
| [middleware/app/services/ai_engine_client.py](middleware/app/services/ai_engine_client.py) | Maps middleware `Event` → `UnifiedEvent` (AI engine schema) and dispatches to Kafka + HTTP |
| [middleware/app/models/event.py](middleware/app/models/event.py) | Inbound event schema (Pydantic) |
| [middleware/app/core/config.py](middleware/app/core/config.py) | `pydantic-settings` configuration (env-driven) |
| [middleware/scripts/auto_alerts.py](middleware/scripts/auto_alerts.py) | Demo event generator (used by the `alert-sender` service) |

### 2.2 `ai-engine/` — scoring service + dashboard backend

A Python package combining:
- **`scoring_service/`** — feature extraction, Isolation Forest, rule
  engine, score fusion, batch + Kafka stream drivers.
- **`backend/`** — FastAPI app exposing the dashboard REST + WebSocket API,
  with an in-memory datastore, an event replay controller, and an embedded
  Kafka consumer thread.
- **`schemas/`** — canonical `UnifiedEvent` / `EnrichedEvent` / `Alert`
  Pydantic models (`extra="forbid"`).
- **`frontend/`** — React + TypeScript SOC dashboard (Vite dev server).

Key files:

| File | Purpose |
|---|---|
| [ai-engine/backend/app.py](ai-engine/backend/app.py) | FastAPI factory, lifespan that starts the Kafka consumer thread alongside HTTP |
| [ai-engine/scoring_service/stream.py](ai-engine/scoring_service/stream.py) | `StreamRunner` — Kafka consumer/producer wrapping the scoring pipeline |
| [ai-engine/scoring_service/pipeline.py](ai-engine/scoring_service/pipeline.py) | End-to-end scoring (features → IF → rules → fusion) |
| [ai-engine/backend/datastore.py](ai-engine/backend/datastore.py) | Thread-safe in-memory store backing the dashboard queries |
| [ai-engine/doc/KAFKA_INTEGRATION.md](ai-engine/doc/KAFKA_INTEGRATION.md) | Full Kafka contract + troubleshooting guide |
| [ai-engine/doc/NODERED_CONTRACT.md](ai-engine/doc/NODERED_CONTRACT.md) | Field-level `UnifiedEvent` contract for upstream producers |

### 2.3 Root orchestration

| File | Purpose |
|---|---|
| [docker-compose.yml](docker-compose.yml) | Zookeeper + Kafka + `kafka-init` (topic creation) + middleware + ai-backend + dashboard + optional alert-sender |
| [DOCKER.md](DOCKER.md) | Compose quick-start |

---

## 3. End-to-end data flow

```
HTTP POST /api/events
        │
        ▼
┌─────────────────────────┐
│  middleware (FastAPI)   │
│  - validates Event      │
│  - normalises → Unified │   Kafka primary
│  - publishes ────────────────────────────┐
│  - HTTP fallback ◀── (only if Kafka KO)  │
└─────────────────────────┘                │
                                           ▼
                              ┌──────────────────────────┐
                              │ Kafka topic: events.raw  │
                              └──────────────────────────┘
                                           │
                                           ▼
                              ┌──────────────────────────┐
                              │ ai-backend consumer      │
                              │  - feature extraction    │
                              │  - Isolation Forest      │
                              │  - rules + fusion        │
                              │  - classification        │
                              └──────────────────────────┘
                                  │                  │
                                  ▼                  ▼
                  events.enriched (Kafka)   alerts.critical (Kafka)
                                  │                  │
                                  └────────┬─────────┘
                                           ▼
                                ┌─────────────────────┐
                                │  Dashboard (React)  │
                                │  - REST + WebSocket │
                                └─────────────────────┘
```

Both the Kafka path and the HTTP fallback eventually call the same
`ScoringPipeline.process_event()`, so query results stay consistent
regardless of which transport is used.

---

## 4. Kafka integration

The streaming layer follows the topic plan declared in section 6.1 of the
team architecture:

| Topic | Producer | Consumer | Retention | Partitions |
|---|---|---|---|---|
| `events.raw` | middleware | ai-backend | 7 days | 3 |
| `events.enriched` | ai-backend | dashboard | 30 days | 3 |
| `alerts.critical` | ai-backend | dashboard, SOC notifications | 90 days | 1 |
| `logs.signed` | (security team) | TimescaleDB | 15 years | 1 |

Topics are created with their target retention by the `kafka-init` one-shot
service (see [docker-compose.yml](docker-compose.yml)). Auto-creation is
disabled at the broker level so that retention guarantees are explicit.

The cluster runs as a single broker on Confluent Platform 7.5 with two
listeners:
- `PLAINTEXT://kafka:9092` — used by other containers
- `PLAINTEXT_HOST://localhost:29092` — used from the host (debug, console
  consumer, …)

**Producer (middleware).** A thread-safe lazy-init publisher
([kafka_producer.py](middleware/app/services/kafka_producer.py)) connects on
the first event, attaches success/error callbacks for delivery visibility,
and is flushed/closed by the FastAPI lifespan on shutdown so messages held
in the `linger_ms` buffer are not lost.

**Consumer (ai-backend).** A daemon thread
([stream.py](ai-engine/scoring_service/stream.py)) polls `events.raw`,
runs each message through the scoring pipeline, and produces to
`events.enriched` and `alerts.critical`. The thread is started by the
FastAPI lifespan when `--kafka-brokers` is provided together with a model
and baselines, and stopped cleanly on shutdown.

For the full contract, retention rationale, and troubleshooting steps, see
[ai-engine/doc/KAFKA_INTEGRATION.md](ai-engine/doc/KAFKA_INTEGRATION.md).

---

## 5. HTTP fallback path

When Kafka is unavailable (e.g. local dev without the broker, or the
broker is restarting), the middleware can additionally `POST` each event
to `http://ai-backend:8000/api/ingest/events`. This endpoint runs the
**same** scoring pipeline as the Kafka consumer but does **not** re-publish
on Kafka — it is a pure debugging / smoke-test path.

The fallback is controlled by `AI_FORWARD_ENABLED`. When both
`KAFKA_ENABLED` and `AI_FORWARD_ENABLED` are true, double-write is
performed (Kafka first, then HTTP). Either path failing is logged but does
not cause the middleware to reject the event.

---

## 6. Running the stack

Prerequisites: Docker Desktop ≥ 24.

```bash
# Build images and start all services in the background
docker compose up --build -d

# Tail logs
docker compose logs -f middleware ai-backend kafka

# Stop and clean volumes
docker compose down -v
```

Services and ports:

| Service | URL |
|---|---|
| Dashboard | http://localhost:5173 |
| AI backend (REST + WS) | http://localhost:8000 |
| Middleware | http://localhost:8010 |
| Kafka (host listener) | `localhost:29092` |

To enable the demo event generator (random scenarios every few seconds):

```bash
docker compose --profile alerts up --build -d
ALERT_INTERVAL=2 ALERT_JITTER=0 docker compose --profile alerts up -d
```

See [DOCKER.md](DOCKER.md) for the short version of these commands.

---

## 7. API surface

### Middleware (`http://localhost:8010`)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/events` | Ingest a normalised event |
| `GET` | `/api/events` | List in-memory events (MVP) |
| `GET` | `/api/alerts` | List alerts |
| `GET` | `/api/health` | Liveness probe |

### AI backend (`http://localhost:8000`)

The full surface is documented in [ai-engine/README.md](ai-engine/README.md). Highlights:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/score/current` | Current global risk score |
| `GET` | `/api/events` | Query enriched events |
| `GET` | `/api/alerts/active` | Active SOC alerts |
| `POST` | `/api/ingest/events` | HTTP fallback for `events.raw` |
| `WS` | `/ws/events` | Live event/alert stream |

---

## 8. Repository layout

```
smart-intrusion-detection/
├── docker-compose.yml          ← Zookeeper, Kafka, kafka-init, app services
├── DOCKER.md                   ← Compose quick-start
│
├── middleware/                 ← FastAPI ingest service
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py             ← lifespan: pre-warm + flush Kafka producer
│   │   ├── api/routes.py       ← /api/events, /api/alerts, /api/health
│   │   ├── core/config.py      ← env-driven settings
│   │   ├── models/             ← Event, Alert
│   │   └── services/
│   │       ├── kafka_producer.py     ← publishes events.raw
│   │       ├── ai_engine_client.py   ← Unified mapping + HTTP fallback
│   │       ├── anomaly_detection.py
│   │       ├── mqtt_consumer.py
│   │       └── risk_engine.py
│   ├── scripts/
│   │   ├── auto_alerts.py      ← demo event generator
│   │   └── simulate_iot.py
│   └── tests/
│
└── ai-engine/                  ← scoring service + dashboard backend
    ├── Dockerfile
    ├── pyproject.toml
    ├── schemas/                ← UnifiedEvent / EnrichedEvent / Alert
    ├── dataset/                ← topology, generators
    ├── features/               ← feature extraction + baselines
    ├── models/                 ← trained Isolation Forest
    ├── fusion/                 ← physical/cyber score fusion
    ├── scoring_service/
    │   ├── pipeline.py         ← end-to-end scoring
    │   ├── stream.py           ← Kafka consumer/producer
    │   ├── batch.py
    │   └── alert_builder.py
    ├── backend/
    │   ├── app.py              ← FastAPI factory, lifespan starts consumer
    │   ├── cli.py              ← CLI launcher (uvicorn + flags)
    │   ├── datastore.py        ← in-memory store
    │   ├── replay.py           ← scripted dataset replay
    │   ├── ws_manager.py       ← WebSocket fan-out
    │   └── routes/             ← REST endpoints
    ├── frontend/               ← React + TypeScript dashboard
    └── doc/
        ├── KAFKA_INTEGRATION.md
        └── NODERED_CONTRACT.md
```

---

## 9. Configuration reference

Both services are env-driven. The defaults below match the values set in
`docker-compose.yml`.

### Middleware

| Variable | Default | Purpose |
|---|---|---|
| `KAFKA_ENABLED` | `true` | Publish on `events.raw` |
| `KAFKA_BROKERS` | `kafka:9092` | Bootstrap servers |
| `KAFKA_TOPIC_RAW` | `events.raw` | Outbound topic |
| `AI_FORWARD_ENABLED` | `true` | Enable HTTP fallback |
| `AI_ENGINE_URL` | `http://ai-backend:8000` | AI engine base URL |
| `BUILDING_ID` | `B1` | Default building tag for normalised events |
| `RISK_THRESHOLD_SUSPECT` | `50` | Suspect threshold (0–100) |
| `RISK_THRESHOLD_CRITICAL` | `80` | Critical threshold (0–100) |

### AI backend

| Variable | Default | Purpose |
|---|---|---|
| `KAFKA_BROKERS` | `kafka:9092` | Bootstrap servers |
| `KAFKA_TOPIC_RAW` | `events.raw` | Inbound topic |
| `KAFKA_TOPIC_ENRICHED` | `events.enriched` | Outbound enriched topic |
| `KAFKA_TOPIC_ALERTS` | `alerts.critical` | Outbound alerts topic |
| `KAFKA_GROUP` | `ai-engine-scoring` | Consumer group |

The CLI flags exposed by `python -m backend.cli serve` mirror these
variables and are documented in
[ai-engine/backend/cli.py](ai-engine/backend/cli.py).

---

## 10. End-to-end verification

```bash
# 1) Start the stack
docker compose up --build -d

# 2) Confirm topics were created
docker exec smart-kafka kafka-topics --bootstrap-server kafka:9092 --list
# expected: alerts.critical, events.enriched, events.raw, logs.signed

# 3) Confirm the middleware producer is connected
docker logs smart-middleware 2>&1 | grep -i kafka
# expected: "kafka producer connected: kafka:9092"

# 4) In another terminal, tail events.raw
docker exec smart-kafka kafka-console-consumer \
    --bootstrap-server kafka:9092 \
    --topic events.raw --from-beginning

# 5) Send a synthetic event
curl -sS -X POST http://localhost:8010/api/events \
    -H 'Content-Type: application/json' \
    -d '{
      "event_id": "test-001",
      "event_type": "badge_access",
      "source_device": "R-Z3-01",
      "location": "Z3",
      "details": {
        "user_id": "u042",
        "badge_id": "b042",
        "access_result": "DENIED"
      }
    }'

# 6) The JSON appears in step 4's consumer.
#    Middleware logs show "kafka first delivery confirmed: topic=events.raw …".

# 7) Confirm the AI engine consumed it
docker exec smart-kafka kafka-console-consumer \
    --bootstrap-server kafka:9092 \
    --topic events.enriched --from-beginning --max-messages 1

# 8) Open the dashboard
open http://localhost:5173
```

If any step fails, the troubleshooting section of
[ai-engine/doc/KAFKA_INTEGRATION.md](ai-engine/doc/KAFKA_INTEGRATION.md)
walks through the most common causes (broker not ready, `KAFKA_ENABLED`
unset, init container exited too early, etc.).

---

*This document complements the team-level architecture README. For PQC,
TLS, gateway, or simulator details, refer to that document and to the
sibling repositories owned by the security and simulation sub-teams.*
