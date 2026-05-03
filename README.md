# ai-engine — Behavioural intelligence for converged IoT/AI security

Behavioural detection & scoring component of the converged IoT/AI security
project. Ingests events produced by the IoT simulator/Node-RED middleware,
extracts features, scores them with rules + an Isolation Forest, fuses
physical and cyber signals, and exposes a SOC dashboard.

This module covers layers **6, 7, and 8** of the project architecture
(see top-level `ARCHITECTURE.md`): streaming consumer, AI engine,
backend API, and React dashboard.

---

## Project structure

```
ai-engine/
├── schemas/                ← Pydantic event/alert schemas (the contract)
├── dataset/                ← topology + synthetic event generator + 7 attack scenarios
├── features/               ← feature extraction + behavioural baselines
├── models/                 ← Isolation Forest + rules engine
├── evaluation/             ← metrics, threshold sweeps, scenario evaluation
├── fusion/                 ← physical/cyber correlator + fusion scorer
├── scoring_service/        ← end-to-end pipeline (batch + streaming skeleton)
├── backend/                ← FastAPI REST + WebSocket server
├── frontend/               ← React + TypeScript + Tailwind SOC dashboard
├── docs/                   ← contract documents (Node-RED, Kafka)
└── pyproject.toml          ← Python project manifest
```

---

## Prerequisites

- Python ≥ 3.11 (3.12 recommended)
- Node.js ≥ 20 (for the dashboard)
- ~2 GB free disk for generated datasets (only needed locally; not committed)

---

## Install

```bash
# from ai-engine/ root
pip3 install -e ".[dev]"
```

This installs all Python dependencies including FastAPI, scikit-learn,
pandas, pyarrow, and the test framework.

For the dashboard:

```bash
cd frontend
npm install
```

---

## Running tests

```bash
pytest                         # ~208 tests, ~30 seconds
```

Tests cover the schema contract, dataset generation, feature extraction,
both detectors, the fusion scorer, the scoring pipeline, and the
backend API.

---

## End-to-end pipeline (full reproduction)

The following commands take you from zero to a running dashboard with
all seven attack scenarios visible. **None of the intermediate files
are committed** — they are regenerated locally from these commands.

### Step 1 — Generate the synthetic dataset

The dataset is a topology (50 users, 8 zones, 7 doors, 30 devices) plus
30 days of normal baseline activity plus 7 injected attack scenarios.

```bash
# 1.1 — Build topology if not already present
python3 -m dataset.cli build-topology \
    --out dataset/topology/building_b1.yaml

# 1.2 — Generate 30 days of baseline events
python3 -m dataset.cli generate-baseline \
    --topology dataset/topology/building_b1.yaml \
    --start 2026-04-01 \
    --days 30 \
    --seed 42 \
    --out dataset/output/train_baseline.jsonl

# 1.3 — Generate the seven attack scenarios
python3 -m dataset.cli generate-all-scenarios \
    --topology dataset/topology/building_b1.yaml \
    --out-dir dataset/output \
    --seed 42
```

After this you should have `train_baseline.jsonl` plus seven
`test_<scenario>.jsonl` + matching `truth.json` files in `dataset/output/`.

### Step 2 — Learn behavioural baselines

The baselines (per-user typical zones/hours, per-device network statistics)
are computed from the training data and serialised to JSON.

```bash
python3 -m features.cli learn-baselines \
    --topology dataset/topology/building_b1.yaml \
    --events dataset/output/train_baseline.jsonl \
    --out features/output/baselines.json
```

### Step 3 — Extract features for training

```bash
python3 -m features.cli extract \
    --topology dataset/topology/building_b1.yaml \
    --baselines features/output/baselines.json \
    --events dataset/output/train_baseline.jsonl \
    --out features/output/train_features.parquet
```

### Step 4 — Train the Isolation Forest

```bash
python3 -m models.cli train \
    --features features/output/train_features.parquet \
    --out models/trained/isoforest.joblib
```

### Step 5 — Score & fuse the seven scenarios

This is what generates the data the dashboard consumes. The
`scoring_service.cli` command does feature extraction + IF scoring + rules
+ fusion + classification all in one step.

```bash
python3 -m scoring_service.cli score-batch-all \
    --events-dir dataset/output \
    --topology dataset/topology/building_b1.yaml \
    --baselines features/output/baselines.json \
    --model models/trained/isoforest.joblib \
    --out-dir scoring_service/output
```

After this, `scoring_service/output/` contains:

- `test_<scenario>.enriched.jsonl` — every event with `ai_score` + `ai_classification`
- `test_<scenario>.alerts.jsonl` — alerts for SUSPECT/CRITICAL classifications

### Step 6 — Start the backend

```bash
python3 -m backend.cli serve \
    --topology dataset/topology/building_b1.yaml \
    --data-dir scoring_service/output \
    --port 8000
```

The server is now at `http://localhost:8000` with:
- `/api/score/current` — current zone snapshot
- `/api/alerts/active` — open alerts
- `/api/events?zone=Z8` — filtered events
- `/ws/events` — WebSocket live stream
- `/docs` — auto-generated Swagger UI

### Step 7 — Start the dashboard

In a separate terminal:

```bash
cd frontend
npm run dev
```

Open `http://localhost:5173`. The dashboard polls the API every 2–3 s
and connects to the WebSocket for the live event ticker. Vite proxies
`/api` and `/ws` to `:8000`, so no CORS issues in dev.

---

## Quick smoke test

Without rebuilding the entire pipeline, you can verify the test suite
passes and one scenario flows through end-to-end:

```bash
pytest dataset/tests features/tests models/tests fusion/tests scoring_service/tests
```

---

## Reset (start over)

To wipe everything except code and topology:

```bash
rm -rf dataset/output features/output models/trained scoring_service/output backend/output
```

Then re-run the pipeline above.

---

## Evaluation reports

After running the pipeline, you can produce a CSV summary of detector
performance per scenario:

```bash
python3 -m fusion.cli evaluate-all \
    --fused-dir fusion/output \
    --truth-dir dataset/output \
    --out fusion/output/eval_summary.csv
```

Expected output (with the v0.1 calibration): all seven attacks reach
their expected classification level (`forced_door`, `revoked_badge`,
`hybrid_intrusion`, `credential_theft`, `camera_compromise` → CRITICAL;
`badge_off_hours`, `tailgating` → SUSPECT). Zero CRITICAL false
positives on the baseline.

---

## Architecture notes

- **Float32 vs Float64.** The fusion scorer keeps `score_final` in float64
  to preserve exact representation of the 0.7 boundary; using float32
  causes tiny precision artefacts that disagree with downstream Pydantic
  validation. See `fusion/scorer.py` comments.

- **Why "max + proportional bonus" fusion.** The formula is
  `final = combined + 0.30 × peer × (1 - combined)`, which means a
  correlated peer can push a 0.65 SUSPECT into CRITICAL but cannot
  amplify a 0.95 CRITICAL meaningfully. This avoids over-classification.

- **Streaming is a skeleton.** The `scoring_service.stream` module
  defines the Kafka interface but the Kafka calls are stubbed. When the
  Mosquitto/Node-RED team delivers, fill in `_consume`/`_produce_*` per
  the docstrings. See `docs/NODERED_CONTRACT.md` for the message format.

- **In-memory backend by design.** The backend loads JSONL files at
  startup. Production deployments would swap this for a TimescaleDB
  reader; the route handlers do not depend on the storage choice.

---

## Reference documents

- `docs/NODERED_CONTRACT.md` — exact schema and example events the
  Node-RED middleware MUST publish on `events.raw`.
- `frontend/README.md` — dashboard setup details.
- Top-level `ARCHITECTURE.md` (project root, outside `ai-engine/`) —
  full system architecture and decisions.

---

## Authors

Ilyes Belkhir, Sam Bouchet, Alban Robert (AI/scoring/dashboard)
Ryan Zerhouni, Rania El haddaoui (security & PQC, separate scope)