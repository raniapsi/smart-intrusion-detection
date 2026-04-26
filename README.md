# Technical Architecture — Converged IoT/AI Security for Sensitive Buildings

> **Produced by:** Ryan Zerhouni, Rania El haddaoui, Ilyes Belkhir, Sam Bouchet, Alban Robert
> **Version:** 0.1 — Working document (pre-development)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [IoT Layer — Field Data Sources](#2-iot-layer--field-data-sources)
3. [Protocols & Gateway Layer](#3-protocols--gateway-layer)
4. [Security Layer — PKI-free TLS & PQC](#4-security-layer--pki-free-tls--pqc)
5. [Middleware Layer — Normalisation & Correlation](#5-middleware-layer--normalisation--correlation)
6. [Streaming & Storage Layer](#6-streaming--storage-layer)
7. [AI Layer — Behavioural Intelligence](#7-ai-layer--behavioural-intelligence)
8. [Presentation Layer — SOC Dashboard](#8-presentation-layer--soc-dashboard)
9. [End-to-End Data Flow](#9-end-to-end-data-flow)
10. [Technology Stack](#10-technology-stack)
11. [Data Model](#11-data-model)
12. [Attack Scenarios & Expected Responses](#12-attack-scenarios--expected-responses)
13. [Technical Challenges & Open Points](#13-technical-challenges--open-points)

---

## 1. System Overview

The system is organised into **7 functional layers** that communicate unidirectionally (field → decision), with command feedback from the dashboard.

```
┌─────────────────────────────────────────────────────────────┐
│                  [8] SOC DASHBOARD / UI                     │
│              Alerts · Scores · Maps · Logs                  │
└────────────────────────────┬────────────────────────────────┘
                             │ WebSocket / REST
┌────────────────────────────▼────────────────────────────────┐
│              [7] AI ENGINE — Behavioural Analysis           │
│        Normal / Suspect / Critical Scoring · Anomalies      │
└────────────────────────────┬────────────────────────────────┘
                             │ Enriched events
┌────────────────────────────▼────────────────────────────────┐
│         [6] STREAMING & STORAGE — Kafka · TimescaleDB       │
│              Event queue · History · Logs                   │
└────────────────────────────┬────────────────────────────────┘
                             │ Normalised data
┌────────────────────────────▼───────────────────────────────────┐
│       [5] MIDDLEWARE — Node-RED · Mosquitto MQTT Broker        │
│         Aggregation · Normalisation · Physical/Cyber Correlation│
└────────────────────────────┬───────────────────────────────────┘
                             │ Secured stream (TLS/PQC)
┌────────────────────────────▼────────────────────────────────┐
│       [4] SECURITY — PKI-free TLS · PQC (X25519MLKEM768)    │
│      Hybrid tunnels · Tamper-proof logs · Mutual auth       │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│           [3] GATEWAY / EDGE — Local collection             │
│         Filtering · Pre-processing · Offline buffer         │
└──────┬────────────────────-──────────┬──────────────────────┘
       │ MQTT                          │ HTTP
┌──────▼──────────────────────────────-▼──────────────────────┐
│              [2] COMMUNICATION PROTOCOLS                    │
└──────┬──────────┬──────────┬──────────┬─────────────────────┘
       │          │          │          │
┌──────▼──┐ ┌─────▼───┐ ┌───▼───┐ ┌─────▼─────────────────────┐
│ Badge   │ │  Door   │ │Motion │ │Cameras & env. sensors     │
│ readers │ │ sensors │ │detect.│ │(temp, humidity, video)    │
└─────────┘ └─────────┘ └───────┘ └───────────────────────────┘
                   [1] IoT LAYER — FIELD
```

---

## 2. IoT Layer — Field Data Sources (SIMULATED)

> **Deployment context:** no physical hardware. All sensors are emulated by a **Python simulator** running on the host machine. Each sensor type is a process (or thread) that generates events according to a configurable probabilistic model, publishes over MQTT, and can inject attack scenarios on demand.

### 2.1 Simulator architecture

```
simulator/
├── main.py                  ← orchestrator: starts all agents
├── config.yaml              ← building topology (zones, doors, users)
├── agents/
│   ├── badge_agent.py       ← generates badge accesses (normal + anomalies)
│   ├── door_agent.py        ← generates door states (open/close/forced)
│   ├── motion_agent.py      ← generates motion detections
│   ├── camera_agent.py      ← generates video metadata (no real stream)
│   └── network_agent.py     ← generates network events (traffic, scans)
├── scenarios/
│   ├── normal_day.py        ← normal working day (AI baseline)
│   ├── intrusion_physical.py← forced door without badge
│   ├── hybrid_attack.py     ← physical intrusion + simultaneous network scan
│   └── tailgating.py        ← valid badge + double movement
└── mqtt_client.py           ← shared MQTT client (paho-mqtt)
```

### 2.2 Simulation model per agent

**Badge Agent** — generates accesses following a realistic distribution:
```python
# Normal behaviour: Gaussian distribution around working hours
access_time ~ Normal(μ=9h00, σ=45min)  # morning arrival
access_time ~ Normal(μ=18h00, σ=30min) # evening departure

# Injectable anomaly: access at 3:17 AM
# Injectable anomaly: revoked badge, unknown badge
```

**Network Agent** — generates simulated network traffic (no real traffic captured):
```python
# Normal: constant volume per IP, standard ports
# Anomaly: port scan (SYN burst), exfiltration (high outbound volume)
```

### 2.3 Emitted message format (identical to the real case)

Agents publish exactly the same JSON format a real sensor would — Node-RED and the AI layer see no difference.

| Emitted field   | Type      | Description                                        |
|-----------------|-----------|----------------------------------------------------|
| `badge_id`      | string    | Unique badge identifier                            |
| `user_id`       | string    | Associated user                                    |
| `timestamp`     | datetime  | ISO 8601 timestamp                                 |
| `location_id`   | string    | Target zone / door                                 |
| `access_result` | enum      | `GRANTED` / `DENIED` / `TIMEOUT`                  |

**MQTT topics published by the simulator:**
```
building/B1/zone/{zone_id}/badge/{reader_id}     ← badge_agent
building/B1/zone/{zone_id}/door/{door_id}        ← door_agent
building/B1/zone/{zone_id}/motion/{detector_id}  ← motion_agent
building/B1/network/flow                         ← network_agent
building/B1/network/alert                        ← network_agent (anomalies)
```

---

## 3. Protocols & Gateway Layer (SOFTWARE)

> **Deployment context:** no physical gateway. The gateway is a **containerised Python service** that acts as an intermediary between the simulator and the middleware. In a real deployment, this service would run on a Raspberry Pi; here it runs in a Docker container on the same host.

### 3.1 Supported protocols

| Protocol  | Usage in the simulation               | Python library       |
|-----------|---------------------------------------|----------------------|
| **MQTT**  | Simulator → gateway communication     | `paho-mqtt`          |
| **HTTP**  | Gateway → middleware REST API          | `httpx` / `FastAPI`  |

### 3.2 Software gateway — responsibilities

```
[Python Simulator] ──MQTT──► [Gateway Service]
                                    │
                                    ├── JSON format validation (schema)
                                    ├── Deduplication (avoids duplicates)
                                    ├── In-memory buffer (Python queue)
                                    ├── Outgoing TLS encryption (X25519MLKEM768)
                                    └── Publication to Mosquitto Broker
```

**Technology:** Python service (`asyncio` + `paho-mqtt`), Docker containerised.

> **Note:** in this simulated version, the gateway and the simulator run on the same host. The TLS layer is applied nonetheless on local network connections (localhost with TLS) to validate the crypto implementation under realistic conditions.

---

## 4. Security Layer — PKI-free TLS & PQC

### 4.1 PKI-free TLS architecture — Software simulation adaptation

> **Deployment context:** no Secure Element or physical HSM. Keys are generated and stored in **protected files on the local file system** (restricted permissions, encrypted folder). In a real hardware deployment, these same keys would be burned into the SE/HSM at manufacturing. The cryptographic architecture remains identical — only the physical storage changes.

**Simulation / production equivalences:**

| Element             | Production (hardware)                  | Simulation (host PC)                           |
|---------------------|----------------------------------------|------------------------------------------------|
| Private key storage | Secure Element / HSM (non-extractable) | Encrypted `.pem` file (AES-256), permissions 600 |
| Provisioning        | Burned at factory                      | Generation script on first startup             |
| Anti-extraction     | Hardware (physically impossible)       | OS access control + file encryption            |
| Allow-list          | Identical                              | Identical (JSON file of authorised certificates) |

**Key file structure (simulation):**
```
security/
├── ca/
│   ├── ca.crt                  ← root certificate (hybrid ECC-hybrid-MLDSA5)
│   └── ca.key                  ← root private key (hybrid, encrypted)
├── gateway/
│   ├── gateway.crt             ← software gateway identity certificate
│   └── gateway.key             ← hybrid private key (ECC-hybrid-MLDSA5, perm. 600)
├── middleware/
│   ├── middleware.crt          ← middleware identity certificate
│   └── middleware.key          ← hybrid private key (ECC-hybrid-MLDSA5)
└── allowlist.json              ← list of authorised certificates (mTLS without PKI)
```

**Mutual authentication flow (unchanged vs production):**
1. The simulator/gateway presents its certificate → the middleware validates it via the allow-list
2. The middleware presents its certificate → the gateway validates it
3. TLS 1.3 session established with X25519MLKEM768 as the key group

### 4.2 Post-Quantum Cryptography (PQC)

**Algorithms used:**

| Function                   | Retained hybrid algorithm          | Detail                                                                  | NIST Standard       |
|----------------------------|------------------------------------|-------------------------------------------------------------------------|---------------------|
| Key exchange (KEM)         | **X25519MLKEM768**                 | X25519 (classical ECDH) + ML-KEM-768 (Kyber level 3, 192-bit sec.)    | FIPS 203 + RFC 8422 |
| Authentication / Signature | **ECC-hybrid-MLDSA5**              | ECDSA P-384 (classical) + ML-DSA level 5 (256-bit sec. equiv. AES-256) | FIPS 204            |
| Hash / integrity           | **SHA-3 / SHAKE-256**              | Natively quantum-resistant (sponge construction)                        | FIPS 202            |

**X25519MLKEM768 hybrid tunnel principle:**

```
Client (Gateway)                          Server (Middleware)
      │                                          │
      │── ClientHello (TLS 1.3) ───────────────►│
      │   key_share:                             │
      │     X25519   : PK_x25519_client          │
      │     ML-KEM-768 : PK_mlkem_client         │
      │                                          │
      │◄─ ServerHello ──────────────────────────│
      │   key_share:                             │
      │     X25519   : PK_x25519_server          │
      │     ML-KEM-768 : CT_mlkem (ciphertext)   │
      │                                          │
      │  Final shared secret:                    │
      │  SS = KDF(SS_x25519 ║ SS_mlkem)          │
      │  → If x25519 broken: SS_mlkem holds      │
      │  → If ML-KEM broken: SS_x25519 holds     │
      │                                          │
      │══ Encrypted TLS 1.3 session (AES-256-GCM) ══════════│
```

**ECC-hybrid-MLDSA5 hybrid signature principle:**

```
Signature of a log or certificate:
  sig_final = (sig_ECDSA_P384 ║ sig_MLDSA5)

Verification:
  valid if AND ONLY IF sig_ECDSA_P384 AND sig_MLDSA5 are both valid
  → double signature → maximum security over 15 years against quantum threats
```

**Choice of ML-DSA level 5 (ECC-hybrid-MLDSA5):**
ECC-hybrid-MLDSA5 provides security level 5 (equivalent to AES-256), the highest level of the FIPS 204 standard. Justified here because signed logs must remain legally uncontestable over a 15-year period, during which quantum computing power will evolve in an unpredictable manner.

### 4.2.4 Performance optimisation: Hybrid Session Resumption (PSK+DHE)

To offset the computational overhead and message size of the full PQC handshake (ML-KEM-768), the system implements the **TLS 1.3 Session Resumption** mechanism in hybrid mode:
*   **Initial (Full) Handshake**: Full key exchange **X25519 + ML-KEM-768**. After mutual authentication, a session ticket (PSK - Pre-Shared Key) is generated.
*   **Reconnections (Resumption)**: Use of the **PSK** combined with an ephemeral **DHE exchange (X25519)**.

> [!IMPORTANT]
> **Quantum resistance inheritance**: Session resumption does not lose its PQC security. The PSK used during resumption is directly derived from the shared secret established via ML-KEM-768 during the initial handshake. Even if the ephemeral exchange of the reconnection is classical only (X25519), the global secret remains protected by the quantum entropy of the "parent" PSK.

**Benefits:**
- **Performance**: 90% reduction in PQC overhead on reconnections.
- **Perfect Forward Secrecy (PFS)**: Adding the X25519 exchange on each reconnection ensures that the physical theft of a session ticket does not allow past or future sessions to be decrypted.

### 4.3 Log protection

- **Tamper-proof logs:** each entry is signed with the hybrid ECC-hybrid-MLDSA5 → any modification is detectable, including by a future quantum adversary
- **Log encryption at rest:** using the session key derived from X25519MLKEM768 → protected against "harvest now, decrypt later"
- **Qualified timestamping:** timestamp signed by a TSA (Time Stamping Authority) for legal validity
- **Guarantee duration: 15 years** — justified by the choice of ML-DSA level 5 (ECC-hybrid-MLDSA5)

### 4.4 Segmentation Architecture — Double Tunnel Proxy

In order to guarantee strict isolation and cryptography-agnostic management, the flow between the IoT zone and the Middleware is segmented by a **double proxy** device acting as PQC terminations (PQC Terminations):

1.  **Forward Proxy (Gateway/Edge side)**: Intercepts local flows (MQTT/HTTP) and encapsulates them in the outgoing TLS/PQC tunnel.
2.  **Reverse Proxy (Middleware/Cloud side)**: Terminates the PQC tunnel, verifies the client identity, and redirects the decrypted traffic to internal services (Mosquitto Broker, Node-RED).

**Strategic advantages:**
- **Application agnosticism**: Applications (simulator, Node-RED, Kafka) do not need to natively support PQC libraries; they communicate in clear or via classical TLS on secured local interfaces.
- **Defence in depth**: The PQC tunnel acts as a tamper-proof transport layer (Post-Quantum Secure Pipe), isolated from business logic. This architecture relies on strict network segmentation (isolated Docker Networks), ensuring that the PQC tunnel is the only authorised communication vector between the IoT perimeter and the Middleware perimeter. Isolation is reinforced by the use of internal networks (`internal: true`) for the IoT and Middleware perimeters. Only the transit segment between PQC terminals has an exposed network interface, reducing the overall attack surface to the tunnel endpoints only.

---

## 5. Middleware Layer — Normalisation & Correlation

### 5.1 Mosquitto MQTT Broker

**Role:** central message bus receiving all events from the gateways.

**Structured MQTT topics:**
```
building/{building_id}/zone/{zone_id}/badge/{reader_id}
building/{building_id}/zone/{zone_id}/door/{door_id}
building/{building_id}/zone/{zone_id}/motion/{detector_id}
building/{building_id}/network/flow
building/{building_id}/network/alert
```

### 5.2 Node-RED — Orchestration & Normalisation

**Role:** visual flow-based programming platform that consumes MQTT messages and transforms them into normalised events. Node-RED is particularly well-suited to IoT: native MQTT nodes, large community node ecosystem, and lightweight deployment.

**Node-RED flow architecture:**

```
[Flow 1 — Multi-source MQTT ingestion]

  [mqtt in] badge    ──┐
  [mqtt in] door     ──┤
  [mqtt in] motion   ──┼──► [switch] type ──► [function] parser ──► [function] validate
  [mqtt in] camera   ──┤
  [mqtt in] network  ──┘

[Flow 2 — Normalisation & Enrichment]

  [function] validate
      │
      ▼
  [function] normalize        ← reformatting to Unified Event Schema
      │
      ▼
  [http request] GET user     ← internal API call to enrich user_id → name, authorised zone
      │
      ▼
  [function] enrich
      │
      ├──► [kafka out] topic: events.raw
      └──► [function] log_sign ──► [timescaledb out] signed logs

[Flow 3 — Physical / cyber correlation]

  [kafka in] events.raw
      │
      ▼
  [function] time_window_buffer    ← 10s sliding window per zone
      │
      ▼
  [function] correlate             ← detects (badge + network traffic) in same zone/window
      │
      ├── correlation found ──► [function] merge_events ──► [kafka out] events.raw (enriched)
      └── no correlation    ──► pass-through

[Flow 4 — Real-time critical alerts]

  [kafka in] alerts.critical
      │
      ▼
  [switch] classification
      ├── CRITICAL ──► [http request] POST SOC webhook
      │              ► [email out] team notification
      │              ► [websocket out] dashboard
      └── SUSPECT  ──► [websocket out] dashboard (level 2)

[Flow 5 — IoT device health monitoring]

  [inject] timer 30s ──► [http request] GET /devices/status
      │
      ▼
  [function] check_last_seen    ← device silent > threshold = alert
      │
      └── device KO ──► [mqtt out] building/.../device/alert
```

**Node-RED nodes used:**

| Node                              | Source              | Usage                                      |
|-----------------------------------|---------------------|--------------------------------------------|
| `node-red-contrib-mqtt`           | Core                | Subscribe/Publish Mosquitto                |
| `node-red-contrib-kafka`          | Community npm       | Produce/Consume Kafka                      |
| `node-red-contrib-postgresql`     | Community npm       | Write to TimescaleDB                       |
| `node-red-contrib-http-request`   | Core                | Internal REST calls (enrichment)           |
| `node-red-contrib-websocket`      | Core                | Real-time push to dashboard                |
| `function`                        | Core                | Business logic in JavaScript               |
| `switch`                          | Core                | Conditional routing                        |
| `inject`                          | Core                | Time-based triggers (health checks)        |
| `debug`                           | Core                | Flow supervision during development        |

### 5.3 Normalised event format (Unified Event Schema)

```json
{
  "event_id": "uuid-v4",
  "event_type": "BADGE_ACCESS | DOOR_FORCED | MOTION_DETECTED | NETWORK_ANOMALY | ...",
  "source_layer": "PHYSICAL | CYBER",
  "timestamp": "ISO 8601",
  "building_id": "string",
  "zone_id": "string",
  "device_id": "string",
  "user_id": "string | null",
  "severity_raw": "INFO | WARNING | ALERT",
  "payload": { /* raw data specific to event_type */ },
  "correlated_events": ["event_id_1", "event_id_2"],
  "ai_score": null,          // filled by the AI layer
  "ai_classification": null  // "NORMAL" | "SUSPECT" | "CRITICAL"
}
```

---

## 6. Streaming & Storage Layer

### 6.1 Apache Kafka — Real-time streaming

**Role:** high-performance message queue between the middleware and the AI engine. Kafka relies on **Zookeeper** for broker coordination and cluster configuration management.

**Kafka topics:**

| Topic                    | Producer     | Consumer         | Retention |
|--------------------------|--------------|------------------|-----------|
| `events.raw`             | Middleware   | AI Engine        | 7 days    |
| `events.enriched`        | AI Engine    | Dashboard, DB    | 30 days   |
| `alerts.critical`        | AI Engine    | SOC, Notif.      | 90 days   |
| `logs.signed`            | Middleware   | TimescaleDB      | 15 years  |

### 6.2 TimescaleDB — Time-series storage

**Role:** database optimised for time series (PostgreSQL extension).

**Main tables:**

```sql
-- Normalised events
CREATE TABLE events (
  event_id     UUID PRIMARY KEY,
  event_type   VARCHAR(50),
  source_layer VARCHAR(10),
  timestamp    TIMESTAMPTZ NOT NULL,
  building_id  VARCHAR(50),
  zone_id      VARCHAR(50),
  device_id    VARCHAR(50),
  user_id      VARCHAR(50),
  ai_score     FLOAT,
  ai_class     VARCHAR(10),
  payload      JSONB,
  signature    BYTEA  -- PQC log signature
);
SELECT create_hypertable('events', 'timestamp');

-- User behavioural profiles (AI baseline)
CREATE TABLE user_profiles (
  user_id         VARCHAR(50) PRIMARY KEY,
  typical_zones   TEXT[],
  typical_hours   INT4RANGE[],
  avg_duration_s  FLOAT,
  last_updated    TIMESTAMPTZ
);

-- Historical risk scores
CREATE TABLE risk_scores (
  score_id    UUID PRIMARY KEY,
  entity_id   VARCHAR(50),  -- user_id or device_id
  entity_type VARCHAR(10),
  score       FLOAT,
  timestamp   TIMESTAMPTZ NOT NULL
);
SELECT create_hypertable('risk_scores', 'timestamp');
```

---

## 7. AI Layer — Behavioural Intelligence

### 7.1 Processing pipeline

```
Kafka (events.raw)
    │
    ▼
[1] Feature Extraction
    │  → Time, zone, user, duration, frequency, network delta
    ▼
[2] Behavioral Baseline (reference model per user/zone)
    │  → Comparison with historical profile (TimescaleDB)
    ▼
[3] Anomaly Scoring
    │  → Score 0.0 → 1.0 per dimension
    ▼
[4] Cross-Correlation (physical + cyber)
    │  → Fusion of physical and network signals within a time window
    ▼
[5] Risk Classification
    │  → NORMAL (< 0.3) | SUSPECT (0.3–0.7) | CRITICAL (> 0.7)
    ▼
Kafka (events.enriched) + TimescaleDB
```

### 7.2 Models used

| Model                   | Usage                                         | Technology           |
|-------------------------|-----------------------------------------------|----------------------|
| **Isolation Forest**    | Unsupervised anomaly detection                | scikit-learn         |
| **LSTM / Time Series**  | Modelling temporal access sequences           | PyTorch / Keras      |
| **Rule-based engine**   | Deterministic rules (forced door = CRITICAL)  | Python / Node-RED    |
| **Fusion scorer**       | Combination of physical + cyber scores        | Python (learned weights)|

### 7.3 Dynamic risk score

**Fusion formula (to be refined):**
```
score_final = min(1.0, w1 × score_physical + w2 × score_cyber + w3 × score_correlation)
```
- `w1, w2, w3`: weights learned by cross-validation (e.g.: $w3 = 0.2$)
- `score_correlation`: binary variable (1 if `correlated_events` is non-empty, 0 otherwise)

**Classification:**
```
score ∈ [0.0, 0.3)  →  NORMAL    (log only)
score ∈ [0.3, 0.7)  →  SUSPECT   (SOC level 2 alert)
score ∈ [0.7, 1.0]  →  CRITICAL  (immediate alert, automatic action possible)
```

### 7.4 Model Drift

- Periodic retraining on the last 90 days of validated events
- Monitored metrics: false positive rate, false negative rate, score distribution
- A/B testing between old and new model version before deployment

---

## 8. Presentation Layer — SOC Dashboard

### 8.1 Dashboard features

- **Building map view**: zones coloured according to the current risk level
- **Real-time alert feed**: events sorted by score, filters by zone/type/severity
- **User profile page**: access history, evolving risk score, associated events
- **Device profile page**: status of each IoT sensor, health, last communication
- **Correlation timeline**: visualisation of physical + cyber events on a shared time axis
- **Auditable logs**: consultation of PQC-signed logs, export for legal investigation

### 8.2 Frontend stack

| Component     | Technology             |
|---------------|------------------------|
| Framework     | React + TypeScript     |
| Real-time     | WebSocket (Socket.io)  |
| Mapping       | Leaflet.js / SVG floors|
| Charts        | Recharts / D3.js       |
| Backend API   | FastAPI (Python)       |

### 8.3 Backend API (FastAPI)

```
GET  /api/events?zone=&from=&to=&class=
GET  /api/alerts/active
GET  /api/users/{user_id}/profile
GET  /api/devices
GET  /api/score/current
POST /api/alert/{alert_id}/acknowledge
GET  /api/logs?signed=true&from=&to=    (legal export)
WS   /ws/events                         (real-time stream)
```

---

## 9. End-to-End Data Flow

### Nominal scenario — Normal badge access

```
09:02:14  Badge #1042 scanned → Door A3 (server zone)
          → MQTT: building/B1/zone/Z3/badge/R07
          → Gateway: unified JSON format
          → Middleware Node-RED: normalisation, enrichment user "alice@corp"
          → Kafka topic events.raw
          → AI: alice profile = Z3 access expected 8am-6pm, physical score = 0.05
          → Network score: alice traffic normal, cyber score = 0.03
          → Final score = 0.04 → NORMAL
          → TimescaleDB: signed log (ECC-hybrid-MLDSA5)
          → Dashboard: zone Z3 status update (green)
```

### Hybrid attack scenario — Masked intrusion

```
03:17:42  Door B2 (data centre zone) opened without associated badge
          → Door sensor: state=FORCED, no_badge_in_window=true
          → Partial physical score: 0.80 → CRITICAL

03:17:45  Unusual network traffic from camera IP B2-CAM-01
          → Internal port scan detected
          → Cyber score: 0.80

03:17:47  Correlation: same zone B2, 3s time window
          → Correlation penalty: +0.20
          → Final score: min(1.0, 0.80×0.5 + 0.80×0.5 + 0.20) = 1.0
          → CRITICAL

          → Kafka topic alerts.critical
          → SOC notification (SMS + red dashboard)
          → Possible automatic action: lock door B2, isolate camera VLAN
          → Signed log (ECC-hybrid-MLDSA5) archived in TimescaleDB
```

---

## 10. Technology Stack

> **Infrastructure:** everything runs on **a single PC** via **Docker Compose**. Each component is an isolated container. Inter-container communications go through the internal Docker network; TLS is applied even locally to validate the crypto implementation under realistic conditions.

### Target hardware configuration

| Resource  | Recommended minimum    | Main role                               |
|-----------|------------------------|-----------------------------------------|
| CPU       | 8 cores                | Kafka, AI (Isolation Forest), Node-RED  |
| RAM       | 16 GB                  | Kafka + TimescaleDB + all services      |
| Storage   | 20 GB SSD              | TimescaleDB logs (time series)          |
| OS        | Windows 11 / macOS (ARM) | Docker Desktop (Engine 24+)           |

### Docker Compose services

```yaml
# docker-compose.yml — simplified view
services:
  simulator:        # Python agents (badge, door, motion, network)
  mosquitto:        # MQTT Broker
  gateway:          # Python gateway service (validation, TLS)
  nodered:          # Middleware / flow orchestration
  zookeeper:        # Required by Kafka
  kafka:            # Event streaming
  timescaledb:      # Time-series database
  ai-engine:        # Python service: AI scoring
  backend:          # FastAPI API
  frontend:         # React dashboard (served by Nginx)
  grafana:          # System monitoring
  prometheus:       # Metrics collection

networks:
  iot-net:          # Internal Docker network (isolated)
```

### Stack per layer

| Layer            | Component               | Language / Runtime      | Role                                        |
|------------------|-------------------------|-------------------------|---------------------------------------------|
| IoT Simulation   | Python agents           | Python 3.12             | Event generation (badges, doors…)           |
| Protocols        | Mosquitto 2.x           | C                       | MQTT Broker                                 |
| Gateway          | Python asyncio service  | Python 3.12             | Validation, buffer, MQTT publication        |
| TLS/PQC Security | OpenSSL 3.x + liboqs + oqs-python | Python 3.12 | TLS 1.3 + X25519MLKEM768 + ECC-hybrid-MLDSA5   |
| Middleware       | Node-RED (self-hosted)  | Node.js 20              | IoT flow orchestration                      |
| Streaming        | Apache Kafka            | JVM                     | Inter-service message queue                 |
| Storage          | TimescaleDB             | PostgreSQL 16           | Time series + signed logs                   |
| AI Engine        | Python service          | Python 3.12             | scikit-learn (Isolation Forest)             |
| Backend API      | FastAPI                 | Python 3.12             | REST + dashboard WebSocket                  |
| Frontend         | React + TypeScript      | Node.js 20 / Nginx      | SOC Dashboard                               |
| Monitoring       | Grafana + Prometheus    | Go                      | System metrics, pipeline latency            |

---

## 11. Data Model

### 11.1 Metadata Entities (Relational — Standard storage)

```
[ Static Reference Data ]             [ Event Stream (Hypertable) ]

User ──────────┐                      ┌──────────────────────────────────┐
  user_id (PK)  │                      │          TABLE : events          │
  name          │       1:N            │   (Unified normalisation)        │
  clearance_lvl ├──────────────────────┤                                  │
  typical_zones │                      │  event_id (UUID)                 │
                │                      │  timestamp (TIMESTAMPTZ)         │
Zone ───────────┤                      │  event_type (ENUM)               │
  zone_id (PK)  │       1:N            │  source_layer (PHYS/CYBER)       │
  building_id   ├──────────────────────┤  building_id                     │
  risk_level    │                      │  zone_id (FK -> Zone)            │
                │                      │  device_id (FK -> Device)        │
Device ─────────┤                      │  user_id (FK -> User)            │
  device_id (PK)│                      │  ai_score (FLOAT)                │
  zone_id (FK)  │       1:N            │  ai_class (ENUM)                 │
  type          ├──────────────────────┤  payload (JSONB)                 │
  status        │                      │  signature (BYTEA)               │
                │                      └──────────────────────────────────┘
Door ───────────┘                       ▲
  door_id (PK)                          │
  zone_id (FK)  ─────── 1:N ────────────┘
  type
```

### 11.2 Relationship details

- **AI joins**: The AI engine consumes the `events` table and joins with `User` to compare the current event against `typical_zones` and `typical_hours`.
- **Payload richness**: Type-specific data (e.g.: door `state`, badge `access_result`) is stored in the `JSONB` field to keep the main table flexible.
- **Time partitioning (Hypertables)**: To maintain high performance over 15 years, storage uses the hypertable mechanism. Unlike a standard table that saturates with volume, data is split into **autonomous physical partitions ("chunks")** on the hard drive. Each chunk represents a time window (e.g.: 7 days).
  - *Technical benefit*: During a query, the database engine targets only the relevant files (partition exclusion), limiting disk I/O. This ensures that indexes remain "warm" (in RAM) and allows instant deletion of obsolete data by simply dropping a file, without database fragmentation.

---

## 12. Attack Scenarios & Expected Responses

| Scenario                                  | Detected signals                              | Expected score | System response               |
|-------------------------------------------|-----------------------------------------------|----------------|-------------------------------|
| Badge access outside hours                | Badge outside authorised window               | 0.55 SUSPECT   | SOC level 2 alert             |
| Forced door (without badge)               | Door FORCED + no badge                        | 0.80 CRITICAL  | Immediate alert               |
| Tailgating (2 people, 1 badge)            | Motion > 1 person + 1 badge                   | 0.60 SUSPECT   | Alert + camera verification   |
| Revoked badge used                        | Badge DENIED + repeated attempt               | 0.80 CRITICAL  | Alert + legal log             |
| Physical intrusion + network scan         | Door + motion + abnormal traffic              | 1.0 CRITICAL   | Alert + VLAN isolation        |
| IoT camera compromise                     | Abnormal traffic from camera IP               | 0.70 CRITICAL  | Device isolation + alert      |
| Network credential theft after physical access | Badge OK + post-access exfiltration traffic | 0.85 CRITICAL | Correlated alert              |

---

## 13. Technical Challenges & Open Points

### Open points (to be decided as a team)

- [x] **Simulation vs real hardware:** everything simulated on PC — Python multi-agent simulator ✓
- [x] **Deployment:** Docker Compose on a single PC (Windows/Mac) ✓
- [ ] **AI model:** Isolation Forest in v1 → LSTM in v2 if time allows
- [ ] **PQC implementation:** `liboqs` + `oqs-python` — X25519MLKEM768 + ECC-hybrid-MLDSA5 → **Ryan & Rania's scope**
- [ ] **Key storage (simulation):** AES-256 encrypted `.pem` files with passphrase → to be defined by Ryan & Rania
- [ ] **GDPR:** simulation of metadata only, no real video — issue ruled out ✓
- [ ] **Device cert signature:** ECC-hybrid-MLDSA5 (consistent with logs) or ML-DSA-65 (lighter)? → to be decided by Ryan & Rania

### Identified risks

| Risk                                | Probability | Impact | Mitigation                                        |
|-------------------------------------|-------------|--------|---------------------------------------------------|
| End-to-end latency > 1s             | Low         | High   | Everything on the same PC → fast Docker internal network. **Session Resumption (PSK+DHE)** reduces PQC overhead by 90% after the 1st handshake.|
| Excessively high false positives    | High        | Medium | Threshold calibration + operator feedback         |
| AI model drift                      | Medium      | High   | Automatic retraining + metric alerts              |
| RAM saturation (Kafka + TimescaleDB)| Medium      | High   | Docker limits per container, Grafana monitoring   |
| Docker Compose complexity (10+ services) | Medium | Medium | Startup scripts, configured healthchecks          |

---

## Repository Structure (proposal)

```
iot-security/
├── docs/
│   └── ARCHITECTURE.md           ← this file
├── simulator/                     ← layer 1: IoT sensor simulation
│   ├── agents/                   ← badge_agent.py, door_agent.py, etc.
│   ├── scenarios/                ← normal_day.py, hybrid_attack.py, etc.
│   ├── config.yaml               ← simulated building topology
│   └── main.py                   ← simulator orchestrator
├── gateway/                       ← layer 3: software gateway
│   └── gateway.py                ← validation, buffer, MQTT publication
├── security/                      ← layer 4: TLS/PQC — Ryan & Rania's scope
│   ├── ca/                       ← root authority (hybrid)
│   ├── gateway/                  ← Gateway certificates & keys (hybrid)
│   ├── middleware/               ← Middleware certificates & keys (hybrid)
│   ├── tls_client.py             ← TLS client (X25519MLKEM768)
│   ├── tls_server.py             ← TLS server
│   └── log_signer.py             ← ECC-hybrid-MLDSA5 log signing
├── middleware/                    ← layer 5: Node-RED flows
│   └── flows/                    ← exported Node-RED flows.json files
├── ai-engine/                     ← layer 7: AI engine
│   ├── models/                   ← serialised trained models
│   ├── training/                 ← Isolation Forest training scripts
│   └── scoring_service.py        ← Real-time analysis engine (Kafka Consumer)
├── backend/                       ← layer 8: FastAPI
│   └── app/
├── frontend/                      ← layer 8: React dashboard
│   └── src/
├── infra/
│   ├── docker-compose.yml        ← orchestrates all services
│   ├── mosquitto/
│   │   └── mosquitto.conf
│   ├── kafka/
│   └── timescaledb/
│       └── init.sql              ← table + hypertable creation
└── README.md
```

---

## 14. Workload Estimation

An estimated breakdown of development time by major technical area:

| Work theme                           | Load (%) | Description                                                                 |
|--------------------------------------|----------|-----------------------------------------------------------------------------|
| **Security & PQC Cryptography**      | 30%      | Hybrid handshake, Session Resumption PSK+DHE, Double Proxy Terminations.    |
| **Network Architecture & Docker**    | 15%      | Segmentation via isolated Docker Networks (internal:true), orchestration.   |
| **AI Engine & Scoring**              | 15%      | Feature engineering, Isolation Forest, score fusion logic.                  |
| **Middleware & Kafka Pipeline**      | 15%      | Kafka configuration, Node-RED flows, unified normalisation.                 |
| **SOC Dashboard & Visualisation**    | 15%      | React interface, real-time WebSockets, alert mapping.                       |
| **IoT Simulation & Scenarios**       | 10%      | Development of Python agents and attack injection scripts.                  |

---

## 15. Roles and Responsibilities

| Team member | Main role | Key missions | Load (%) |
| :--- | :--- | :--- | :--- |
| **Ryan Zerhouni & Rania El haddaoui** | **Security & PQC Lead (Cyber Part)** | Hybrid handshake, Session Resumption, Double Proxy, PQC signing. | 30% |
| **Ilyes Belkhir, Sam Bouchet & Alban Robert** | **AI & Scoring Expert** | Feature engineering, Isolation Forest model and score fusion. | 15% |
| **Ilyes Belkhir, Sam Bouchet & Alban Robert** | **Infra & Simulation Lead** | Docker orchestration, network isolation (`internal: true`), simulator. | 25% |
| **Ilyes Belkhir, Sam Bouchet & Alban Robert** | **Data Engineer** | Node-RED flows, Unified Schema normalisation and Kafka. | 15% |
| **Ilyes Belkhir, Sam Bouchet & Alban Robert** | **Frontend & SOC Lead** | React dashboard, real-time WebSockets and SOC mapping. | 15% |

---

*Document last updated on 25/04/2026 — Validated by the team.*