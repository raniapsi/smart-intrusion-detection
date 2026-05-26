FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY schemas ./schemas
COPY dataset ./dataset
COPY features ./features
COPY models ./models
COPY evaluation ./evaluation
COPY fusion ./fusion
COPY scoring_service ./scoring_service
COPY backend ./backend
COPY features/output/baselines.json ./features/output/baselines.json
COPY models/trained/isoforest.joblib ./models/trained/isoforest.joblib

RUN pip install -e .

EXPOSE 8000

CMD ["python", "-m", "backend.cli", "serve", "--topology", "dataset/topology/building_b1.yaml", "--baselines", "features/output/baselines.json", "--model", "models/trained/isoforest.joblib", "--host", "0.0.0.0", "--port", "8000", "--no-replay"]
