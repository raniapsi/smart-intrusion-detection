-- TimescaleDB init — iot_security database
-- Architecture.md §6.2 + §11
-- Runs once on first container start (docker-entrypoint-initdb.d)

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ── Static reference tables (relational) ─────────────────────────────────────

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id         VARCHAR(50) PRIMARY KEY,
    typical_zones   TEXT[],
    typical_hours   INT4RANGE[],
    avg_duration_s  FLOAT,
    last_updated    TIMESTAMPTZ
);

-- ── Time-series tables (hypertables) ─────────────────────────────────────────

-- Normalised events — one row per UnifiedEvent from events.raw
-- ai_score / ai_classification filled by AI engine after scoring
CREATE TABLE IF NOT EXISTS events (
    event_id     UUID        NOT NULL,
    PRIMARY KEY (event_id, timestamp),
    event_type   VARCHAR(50) NOT NULL,
    source_layer VARCHAR(10) NOT NULL,  -- PHYSICAL | CYBER
    timestamp    TIMESTAMPTZ NOT NULL,
    building_id  VARCHAR(50),
    zone_id      VARCHAR(50),
    device_id    VARCHAR(50),
    user_id      VARCHAR(50),
    ai_score     FLOAT,
    ai_class     VARCHAR(10),           -- NORMAL | SUSPECT | CRITICAL
    payload      JSONB,
    signature    BYTEA                  -- PQC log signature (ECC-hybrid-MLDSA5)
);

SELECT create_hypertable('events', 'timestamp', if_not_exists => TRUE);

-- Historical risk scores per entity (user or device)
CREATE TABLE IF NOT EXISTS risk_scores (
    score_id    UUID        NOT NULL,
    PRIMARY KEY (score_id, timestamp),
    entity_id   VARCHAR(50) NOT NULL,   -- user_id or device_id
    entity_type VARCHAR(10) NOT NULL,   -- USER | DEVICE
    score       FLOAT       NOT NULL,
    timestamp   TIMESTAMPTZ NOT NULL
);

SELECT create_hypertable('risk_scores', 'timestamp', if_not_exists => TRUE);

-- ── Indexes ───────────────────────────────────────────────────────────────────

-- Fast lookup by zone, device, user on the events hypertable
CREATE INDEX IF NOT EXISTS idx_events_zone     ON events (zone_id,   timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_device   ON events (device_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_user     ON events (user_id,   timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_type     ON events (event_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_aiclass  ON events (ai_class,  timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_risk_entity ON risk_scores (entity_id, timestamp DESC);
