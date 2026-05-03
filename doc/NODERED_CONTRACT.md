# events.raw — Node-RED Output Contract

> **Audience:** team members responsible for the Mosquitto broker, the
> simulator, and the Node-RED middleware (layers 2–5 of the architecture).
>
> **Purpose:** define exactly what the AI engine expects on Kafka topic
> `events.raw`, so the two halves of the project can be developed in
> parallel and integrate seamlessly when Kafka is wired up (step 9).

---

## 1. The contract in one sentence

Every message published on `events.raw` MUST be a single JSON object that
validates against the `UnifiedEvent` Pydantic schema defined in
`ai-engine/schemas/events.py`. One JSON object per Kafka record. UTF-8
encoding. No trailing newline required, no envelope, no headers other
than what Kafka adds itself.

---

## 2. Why this matters

The AI engine validates EVERY incoming event with `extra="forbid"`,
which means **any unknown field will cause the event to be rejected
immediately**. This is intentional: it protects the AI pipeline from
silently consuming malformed data and helps catch contract drift as
early as possible.

If a Node-RED flow adds a debug field, a timestamp in the wrong format,
or a typo in an enum value, the consumer will log a validation error
and the event is dropped. There is no "fallback" or "best effort"
parsing — the schema is the contract.

---

## 3. Required JSON fields

Every event MUST contain ALL of the following top-level fields:

| Field                  | Type                | Notes                                                    |
|------------------------|---------------------|----------------------------------------------------------|
| `event_id`             | string (UUID v4)    | Globally unique. Generate one per emitted event.         |
| `event_type`           | string (enum)       | See section 4.                                            |
| `source_layer`         | string (enum)       | `"PHYSICAL"` or `"CYBER"`                                 |
| `timestamp`            | string (ISO 8601)   | UTC, with timezone suffix (e.g. `Z` or `+00:00`)         |
| `building_id`          | string              | Always `"B1"` for this project                            |
| `zone_id`              | string              | Must match a zone defined in `building_b1.yaml`          |
| `device_id`            | string              | The reader / sensor / camera that emitted the event      |
| `user_id`              | string \| null      | Optional. Set when a user is identified, else `null`.    |
| `severity_raw`         | string (enum)       | `"INFO"`, `"WARNING"`, or `"ALERT"`                       |
| `payload`              | object              | Type-specific structure — see section 5.                  |
| `correlated_events`    | array of UUIDs      | May be empty (`[]`). Reserved for upstream correlation.  |
| `schema_version`       | string              | `"1.0.0"` for the current schema                         |
| `ingestion_timestamp`  | string (ISO 8601)   | When the gateway received the raw event (UTC)            |

Two fields are PROHIBITED in `events.raw` (the AI engine FILLS them in):

- `ai_score` — must NOT be present
- `ai_classification` — must NOT be present

If you include them, the message is rejected.

---

## 4. Allowed `event_type` values

The schema accepts exactly these strings:

```
BADGE_ACCESS
DOOR_OPENED
DOOR_CLOSED
DOOR_FORCED
MOTION_DETECTED
NETWORK_FLOW
NETWORK_ANOMALY
CAMERA_EVENT
DEVICE_STATUS
```

Anything else is rejected.

---

## 5. The `payload` structure (discriminated union)

The `payload` field is a discriminated union: its `kind` MUST equal
`event_type`. This is enforced by a model validator. Concretely:

- if `event_type == "BADGE_ACCESS"`, then `payload.kind == "BADGE_ACCESS"`
- if `event_type == "DOOR_FORCED"`, then `payload.kind == "DOOR_FORCED"`
- and so on for every event_type

Below are the per-type payload shapes. Field names and types must match
exactly (Pydantic v2 with `extra="forbid"`).

### 5.1 BADGE_ACCESS

```json
{
  "kind": "BADGE_ACCESS",
  "badge_id": "b042",
  "reader_device_id": "R-Z3-01",
  "access_result": "GRANTED"
}
```

`access_result` ∈ {`"GRANTED"`, `"DENIED"`, `"TIMEOUT"`}.

### 5.2 DOOR_OPENED / DOOR_CLOSED / DOOR_FORCED

```json
{
  "kind": "DOOR_FORCED",
  "door_id": "D-Z2-Z8",
  "duration_open_seconds": 12.4
}
```

`duration_open_seconds` is optional (may be omitted or `null`).

### 5.3 MOTION_DETECTED

```json
{
  "kind": "MOTION_DETECTED",
  "detector_device_id": "M-Z2-01",
  "entity_count": 1
}
```

`entity_count` is optional. When present, it MUST be an integer ≥ 1.

### 5.4 NETWORK_FLOW

```json
{
  "kind": "NETWORK_FLOW",
  "src_ip": "10.42.8.13",
  "dst_ip": "10.42.0.5",
  "dst_port": 443,
  "protocol": "TCP",
  "bytes_sent": 12480,
  "bytes_received": 1024,
  "duration_seconds": 1.2,
  "distinct_dst_ports": null
}
```

- `protocol` ∈ {`"TCP"`, `"UDP"`, `"ICMP"`}
- `bytes_sent`, `bytes_received` are integers ≥ 0
- `dst_port` is 0–65535
- `distinct_dst_ports` is optional (used only when the upstream computes
  it; the AI engine recomputes it from the device's history regardless)

### 5.5 NETWORK_ANOMALY

```json
{
  "kind": "NETWORK_ANOMALY",
  "label": "PORT_SCAN",
  "evidence": "syn_burst_to_50_ports_in_5s"
}
```

`label` ∈ {`"PORT_SCAN"`, `"EXFILTRATION"`, `"C2_BEACON"`,
`"LATERAL_MOVEMENT"`, `"DOS"`, `"UNKNOWN"`}.

### 5.6 CAMERA_EVENT

```json
{
  "kind": "CAMERA_EVENT",
  "camera_device_id": "CAM-Z8-01",
  "event_subtype": "MOTION_DETECTED",
  "snapshot_url": null
}
```

`event_subtype` is a free string (e.g. `"MOTION_DETECTED"`,
`"FACE_DETECTED"`). `snapshot_url` is optional.

### 5.7 DEVICE_STATUS

```json
{
  "kind": "DEVICE_STATUS",
  "status": "OFFLINE",
  "last_heartbeat": "2026-04-15T08:32:11Z"
}
```

`status` ∈ {`"ONLINE"`, `"OFFLINE"`, `"DEGRADED"`}.

---

## 6. MQTT → Kafka mapping

The current architecture (README section 3) routes events as:

```
[Simulator]
   |
   | MQTT topic: building/B1/zone/{zone}/badge/{reader}      (and similar)
   v
[Mosquitto Broker]
   |
   v
[Node-RED middleware]
   |  - normalises into UnifiedEvent
   |  - validates the payload kind
   |  - publishes to Kafka
   v
[Kafka topic: events.raw]   <-- THIS is the contract document point
   |
   v
[AI engine ScoringPipeline]
```

**Recommendation for Node-RED:** add a final `validate` function node
that runs the JSON through a schema check before publishing to Kafka.
The Pydantic schema is duplicable in JS form (a JSON Schema export will
be added; for now the easiest path is to TRY/CATCH a single validation
call to a tiny Python sidecar, or write defensive JS that mirrors the
field list above). Let me know if you want a JSON Schema export.

---

## 7. End-to-end example

A complete BADGE_ACCESS event as it should appear on `events.raw`:

```json
{
  "event_id": "f4a8c2e0-5b3d-4e7a-9c1f-2d8a6b0e1f3c",
  "event_type": "BADGE_ACCESS",
  "source_layer": "PHYSICAL",
  "timestamp": "2026-04-15T09:02:14.512Z",
  "building_id": "B1",
  "zone_id": "Z3",
  "device_id": "R-Z3-01",
  "user_id": "u042",
  "severity_raw": "INFO",
  "payload": {
    "kind": "BADGE_ACCESS",
    "badge_id": "b042",
    "reader_device_id": "R-Z3-01",
    "access_result": "GRANTED"
  },
  "correlated_events": [],
  "schema_version": "1.0.0",
  "ingestion_timestamp": "2026-04-15T09:02:14.598Z"
}
```

---

## 8. Quick acceptance test

Before pointing your Node-RED flow at our Kafka, please run this
locally to confirm your event format. Pipe one of your generated
events through the AI engine batch driver:

```bash
# create a one-event JSONL file with your sample
echo '<your event JSON>' > sample.jsonl

# the validator runs on every line, will fail loudly on any mismatch
python3 -m scoring_service.cli score-batch \
    --events sample.jsonl \
    --topology dataset/topology/building_b1.yaml \
    --baselines features/output/baselines.json \
    --model models/trained/isoforest.joblib \
    --enriched-out /tmp/test.enriched.jsonl \
    --alerts-out /tmp/test.alerts.jsonl
```

If `/tmp/test.enriched.jsonl` ends up with one line containing your
event with `ai_score` and `ai_classification` filled in, the format is
correct. If you get a `ValidationError`, the message will say exactly
which field is wrong.

---

## 9. Versioning & change procedure

The `schema_version` field is `"1.0.0"`. Any breaking change to the
event format MUST bump this version. Coordinate breaking changes via
team review — the AI engine declares its accepted versions explicitly.

Compatible (non-breaking) additions are allowed but require updating
both sides simultaneously, because of `extra="forbid"`.

---

*Maintained by Ilyes — last updated alongside step 8 of the AI engine.*