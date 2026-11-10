"""Dev-only endpoints that let you break the fake world from the dashboard."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.queue.stream import publish
from app.schemas import AlertIn
from app.services.events import emit
from app.services.incidents import create_or_attach, supersede_open
from victim.generate import SCENARIOS
from victim.loader import load_scenario

router = APIRouter(prefix="/dev", tags=["dev"])


@router.get("/scenarios")
async def list_scenarios():
    return [{"name": name, "description": spec["description"]} for name, spec in SCENARIOS.items()]


@router.post("/scenarios/{name}")
async def run_scenario(name: str, session: AsyncSession = Depends(get_session)):
    if name not in SCENARIOS:
        raise HTTPException(status_code=404, detail="unknown scenario")

    data = await asyncio.to_thread(load_scenario, name, settings.database_url)
    alert = AlertIn(**data["alert"])

    await supersede_open(session, alert.service, alert.alert_name)
    incident, created = await create_or_attach(session, alert)
    await emit(incident.id, "api", "alert_received", f"Alert received: {alert.summary}")
    await publish({"type": "alert", "incident_id": str(incident.id)})
    return {"incident_id": str(incident.id), "scenario": name}
