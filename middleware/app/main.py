import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import settings
from app.services.kafka_producer import publisher as kafka_publisher

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.KAFKA_ENABLED:
        producer = kafka_publisher._ensure()
        if producer is None:
            logger.warning(
                "kafka enabled but producer init failed at startup; "
                "publishes will be retried lazily and may no-op",
            )
    try:
        yield
    finally:
        kafka_publisher.close(timeout=5.0)


app = FastAPI(
    title=settings.APP_NAME,
    description="Intelligent Intrusion Detection for Sensitive Buildings",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    return {"message": "Smart Intrusion Detection API is running"}
