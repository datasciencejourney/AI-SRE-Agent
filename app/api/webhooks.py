from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.tokens import verify
from app.db.session import get_session
from app.queue.stream import publish
from app.schemas import AlertIn
from app.services.events import emit
from app.services.incidents import create_or_attach

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/alert")
async def receive_alert(
    request: Request,
    x_signature: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
):
    body = await request.body()
    if not verify(settings.webhook_secret, body, x_signature):
        raise HTTPException(status_code=401, detail="bad signature")

    try:
        alert = AlertIn.model_validate_json(body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors(include_url=False))

    incident, created = await create_or_attach(session, alert)
    if created:
        await emit(incident.id, "api", "alert_received", f"Alert received: {alert.summary}")
        await publish({"type": "alert", "incident_id": str(incident.id)})
    else:
        await emit(incident.id, "api", "duplicate_alert", "Same alert fired again, attached to this incident")
    return {"incident_id": str(incident.id), "created": created}
