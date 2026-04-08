# Smart Intrusion Detection

Intelligent intrusion detection system for sensitive buildings (laboratories, data centers, server rooms). Combines **IoT sensors**, **cybersecurity monitoring**, and **AI-based anomaly detection** to detect hybrid threats in near real time.

## Overview

Traditional security systems handle badge access, cameras, door sensors, and network monitoring separately. This project **unifies** these signals and correlates physical + cyber events to compute a dynamic risk score.

### Alert classification

| Level | Score | Description |
|-------|-------|-------------|
| Normal | 0–49 | No threat detected |
| Suspect | 50–79 | Unusual activity, requires attention |
| Critical | 80–100 | High-risk intrusion, immediate response |

## Architecture

```
IoT Devices (simulated)
        │
        ▼
   MQTT (Mosquitto)
        │
        ▼
   Node-RED (middleware)
        │
        ▼
   FastAPI Backend ◄──► AI / Risk Engine
        │
        ▼
   Alerts & Dashboard
```

## Tech Stack

- **Backend**: Python, FastAPI, Pydantic, Uvicorn
- **Messaging**: MQTT, Mosquitto
- **Middleware**: Node-RED
- **AI**: pandas, numpy, scikit-learn
- **Database**: PostgreSQL (planned)

## Project Structure

```
smart-intrusion-detection/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── api/routes.py         # API endpoints
│   ├── core/config.py        # Configuration (env vars)
│   ├── core/security.py      # Security utilities
│   ├── models/event.py       # IoT/cyber event models
│   ├── models/alert.py       # Alert models
│   ├── services/             # Business logic (MQTT, AI, risk)
│   └── utils/logger.py       # Logging
├── tests/test_api.py         # API tests
├── scripts/simulate_iot.py   # IoT device simulator
├── requirements.txt
├── .env.example
└── .gitignore
```

## Quick Start

### 1. Clone and set up

```bash
git clone https://github.com/dohaab14/muslimINT.git
cd smart-intrusion-detection
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your settings
```

### 3. Run the API

```bash
uvicorn app.main:app --reload
```

API available at: http://localhost:8000  
Swagger docs: http://localhost:8000/docs

### 4. Run the IoT simulator

```bash
python -m scripts.simulate_iot
```

### 5. Run tests

```bash
pytest tests/
```

## MVP Scenario

1. Virtual badge used late at night in restricted zone
2. Door opens
3. Motion detected
4. Abnormal network traffic from IoT device
5. AI engine correlates events → risk score computed
6. Alert generated: **CRITICAL**

## License

This project is for academic purposes.
