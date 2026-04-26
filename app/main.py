from fastapi import FastAPI
from app.api.routes import router
from app.core.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    description="Intelligent Intrusion Detection for Sensitive Buildings",
    version="0.1.0",
)

app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    return {"message": "Smart Intrusion Detection API is running"}
