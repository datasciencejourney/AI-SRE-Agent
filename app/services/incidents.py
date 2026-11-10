import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fingerprint import make_fingerprint
from app.db.models import Alert, Incident
from app.db.session import SessionLocal
from app.schemas import AlertIn

OPEN_STATUSES = ("open", "investigating", "awaiting_approval", "executing")
FINAL_STATUSES = ("resolved", "closed_no_action", "escalated", "superseded")


async def create_or_attach(session: AsyncSession, alert: AlertIn) -> tuple[Incident, bool]:
    """Attach the alert to an open incident with the same fingerprint, or open a new one."""
    fingerprint = make_fingerprint(alert.service, alert.alert_name)

    result = await session.execute(
        select(Incident).where(
            Incident.fingerprint == fingerprint,
            Incident.status.in_(OPEN_STATUSES),
        )
    )
    incident = result.scalars().first()
    created = incident is None

    if created:
        incident = Incident(
            fingerprint=fingerprint,
            service=alert.service,
            title=f"{alert.alert_name}: {alert.summary}",
        )
        session.add(incident)
        await session.flush()  # we need the id before saving the alert

    session.add(Alert(incident_id=incident.id, payload=alert.model_dump(mode="json")))
    await session.commit()
    return incident, created


async def supersede_open(session: AsyncSession, service: str, alert_name: str) -> None:
    """Dev helper: close older incidents of the same kind so a re-run starts fresh."""
    fingerprint = make_fingerprint(service, alert_name)
    await session.execute(
        update(Incident)
        .where(Incident.fingerprint == fingerprint, Incident.status.in_(OPEN_STATUSES + ("escalated",)))
        .values(status="superseded")
    )
    await session.commit()


async def update_incident(incident_id, **fields) -> None:
    if isinstance(incident_id, str):
        incident_id = uuid.UUID(incident_id)
    async with SessionLocal() as session:
        await session.execute(update(Incident).where(Incident.id == incident_id).values(**fields))
        await session.commit()


async def get_incident(incident_id) -> Incident | None:
    if isinstance(incident_id, str):
        incident_id = uuid.UUID(incident_id)
    async with SessionLocal() as session:
        return await session.get(Incident, incident_id)


def now() -> datetime:
    return datetime.now(timezone.utc)
