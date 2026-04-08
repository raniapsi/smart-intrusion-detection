from pydantic_settings import BaseSettings


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

    RISK_THRESHOLD_SUSPECT: int = 50
    RISK_THRESHOLD_CRITICAL: int = 80

    class Config:
        env_file = ".env"


settings = Settings()
