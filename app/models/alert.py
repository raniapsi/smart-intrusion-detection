from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class AlertLevel(str, Enum):
    NORMAL = "normal"
    SUSPECT = "suspect"
    CRITICAL = "critical"


class Alert(BaseModel):
    alert_id: str = Field(..., description="Unique alert identifier")
    level: AlertLevel
    risk_score: float = Field(..., ge=0, le=100, description="Computed risk score")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    related_events: list[str] = Field(default_factory=list, description="List of correlated event IDs")
    description: str = Field(default="", description="Human-readable alert summary")
