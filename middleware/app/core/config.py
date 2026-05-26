from pathlib import Path

from pydantic_settings import BaseSettings


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    APP_NAME: str = "smart-intrusion-detection"
    APP_ENV: str = "development"
    DEBUG: bool = True

    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000

    MQTT_BROKER_HOST: str = "localhost"
    MQTT_BROKER_PORT: int = 1883
    MQTT_USERNAME: str = ""
    MQTT_PASSWORD: str = ""

    DATABASE_URL: str = "postgresql://user:password@localhost:5432/intrusion_db"

    # AI engine forwarding — two paths supported:
    #   - HTTP fallback (AI_FORWARD_ENABLED + AI_ENGINE_URL)
    #   - Kafka producer (KAFKA_ENABLED + KAFKA_BROKERS)
    # Both can be enabled simultaneously (double-write); HTTP serves as a
    # fallback in case the Kafka cluster is down.
    AI_ENGINE_URL: str = "http://127.0.0.1:8000"
    AI_FORWARD_ENABLED: bool = False
    BUILDING_ID: str = "B1"

    # Kafka — when KAFKA_ENABLED, every event accepted by the middleware is
    # also published on the events.raw topic. This is the canonical path
    # described in the project's reference architecture (README section 6).
    KAFKA_ENABLED: bool = False
    KAFKA_BROKERS: str = "localhost:9092"
    KAFKA_TOPIC_RAW: str = "events.raw"
    KAFKA_TOPIC_LOGS_SIGNED: str = "logs.signed"

    RISK_THRESHOLD_SUSPECT: int = 50
    RISK_THRESHOLD_CRITICAL: int = 80

    class Config:
        env_file = ENV_FILE


settings = Settings()