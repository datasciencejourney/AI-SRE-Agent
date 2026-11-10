import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AlertIn(BaseModel):
    alert_name: str
    service: str
    status: str = "firing"
    fired_at: datetime
    summary: str
    labels: dict[str, str] = {}


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    service: str
    title: str
    severity: str
    status: str
    opened_at: datetime
    resolved_at: datetime | None
    root_cause: str | None
    confidence: float | None
    hypothesis: dict | None
    proposed_action: dict | None


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str = ""
    decided_by: str = "dashboard"
