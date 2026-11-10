import uuid

from app.db.models import AgentEvent
from app.db.session import SessionLocal


async def emit(incident_id, agent: str, event_type: str, message: str, **extra) -> None:
    """Store one timeline event. The dashboard picks it up over SSE."""
    if isinstance(incident_id, str):
        incident_id = uuid.UUID(incident_id)
    payload = {"message": message, **extra}
    async with SessionLocal() as session:
        session.add(AgentEvent(incident_id=incident_id, agent=agent, event_type=event_type, payload=payload))
        await session.commit()
