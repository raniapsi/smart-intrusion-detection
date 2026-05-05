# Kafka Integration Guide

> **Status:** Kafka is the canonical event bus per README section 6. The
> middleware publishes on `events.raw`; the AI engine consumes that
> topic, scores events, and produces to `events.enriched` and
> `alerts.critical`. HTTP `/api/ingest/events` remains as a fallback for
> debugging and curl-driven demos.

---

## 1. Topics

The four canonical topics declared in the project's reference architecture:

| Topic              | Producer    | Consumer                  | Retention | Partitions |
|--------------------|-------------|---------------------------|-----------|------------|
| `events.raw`       | middleware  | ai-backend                | 7 days    | 3          |
| `events.enriched`  | ai-backend  | dashboard, TimescaleDB    | 30 days   | 3          |
| `alerts.critical`  | ai-backend  | SOC notifications, dashboard | 90 days   | 1          |
| `logs.signed`      | middleware  | TimescaleDB (audit)       | 15 years  | 1          |

Topic creation is automated by the `kafka-init` service in the root
`docker-compose.yml`; retention values are declared at topic creation
time. See `infra/kafka-topics.sh` if you want to recreate topics on a
running cluster.

---

## 2. Wire format

`events.raw`, `events.enriched`, and `alerts.critical` use the same JSON
schema for their payloads as the HTTP path:

- `events.raw` → `UnifiedEvent` (see `ai-engine/schemas/events.py`)
- `events.enriched` → `EnrichedEvent` (`UnifiedEvent` + `ai_score` + `ai_classification`)
- `alerts.critical` → `Alert` (see `ai-engine/schemas/alerts.py`)
- `logs.signed` → reserved for the security team's PQC-signed log envelope; see `NODERED_CONTRACT.md` for the unsigned format

Encoding: UTF-8, one JSON object per Kafka record. No envelope, no
headers other than what Kafka itself adds. The AI engine validates every
incoming message with `extra="forbid"` Pydantic models — see
`NODERED_CONTRACT.md` for the field-level contract.

---

## 3. Configuration

### AI engine

Pass `--kafka-brokers <hosts>` to the backend CLI:

```bash
python3 -m backend.cli serve \
    --topology dataset/topology/building_b1.yaml \
    --baselines features/output/baselines.json \
    --model models/trained/isoforest.joblib \
    --kafka-brokers kafka:9092 \
    --port 8000
```

Or via environment variables (used by Docker):

```
KAFKA_BROKERS=kafka:9092
KAFKA_TOPIC_RAW=events.raw
KAFKA_TOPIC_ENRICHED=events.enriched
KAFKA_TOPIC_ALERTS=alerts.critical
KAFKA_GROUP=ai-engine-scoring
```

When `--kafka-brokers` is set together with `--baselines` and `--model`,
the FastAPI app starts a daemon thread that consumes `events.raw` in
parallel with serving HTTP. The thread shuts down cleanly with the app.

For a standalone consumer (no FastAPI), use the scoring service CLI:

```bash
python3 -m scoring_service.cli stream \
    --topology dataset/topology/building_b1.yaml \
    --baselines features/output/baselines.json \
    --model models/trained/isoforest.joblib \
    --kafka-brokers kafka:9092
```

### Middleware

```
KAFKA_ENABLED=true
KAFKA_BROKERS=kafka:9092
KAFKA_TOPIC_RAW=events.raw
AI_FORWARD_ENABLED=true       # also keep the HTTP fallback running
AI_ENGINE_URL=http://ai-backend:8000
```

When `KAFKA_ENABLED=true`, every accepted event is published on
`events.raw`. When both `KAFKA_ENABLED` and `AI_FORWARD_ENABLED` are
true, double-write is performed: Kafka first (canonical), then HTTP
(fallback). Either failing is logged but does not cause the middleware
to reject the originating event.

---

## 4. End-to-end test

Once `docker compose up --build` is running:

```bash
# 1) Send a synthetic event to the middleware (HTTP API).
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

# 2) Watch the event hit Kafka:
docker exec smart-kafka kafka-console-consumer \
    --bootstrap-server kafka:9092 \
    --topic events.raw --from-beginning --max-messages 1

# 3) Watch the enriched event come back from the AI engine:
docker exec smart-kafka kafka-console-consumer \
    --bootstrap-server kafka:9092 \
    --topic events.enriched --from-beginning --max-messages 1

# 4) See it on the dashboard:
open http://localhost:5173
```

---

## 5. Troubleshooting

**`kafka-init` exits with `Topic already exists`** — that's normal on
restart, the `--if-not-exists` flag prevents the error. The topics keep
the original retention.

**AI backend logs `kafka stream crashed`** — check that `kafka:9092` is
reachable from inside the container (`docker exec smart-ai-backend nc
-zv kafka 9092`). The most common cause is starting the AI backend
before `kafka-init` has run; the compose file already declares the
proper `depends_on: condition: service_completed_successfully` to
prevent this.

**Middleware logs `kafka publish failed`** — the middleware will
silently fall back to HTTP if `AI_FORWARD_ENABLED=true`. Check the
broker reachability the same way as above. If both Kafka and HTTP fail,
the event stays in the middleware's in-memory store but is not scored.

**Dashboard doesn't update on Kafka events** — verify the AI backend
healthcheck (`curl http://localhost:8000/api/score/current`). The
WebSocket broadcast hook is wired the same way for both Kafka and HTTP
paths, so a green healthcheck implies the issue is upstream of the AI
engine (no events reaching `events.raw`).

---

*Maintained alongside the AI engine's NODERED_CONTRACT.md — they describe
the same wire format, the present document focuses on the Kafka transport
specifics.*