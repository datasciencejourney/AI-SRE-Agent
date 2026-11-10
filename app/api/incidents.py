import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.tokens import approval_message, sign
from app.db.models import AgentEvent, Approval, Incident, Postmortem
from app.db.session import SessionLocal, get_session
from app.queue.stream import publish
from app.schemas import DecisionIn, IncidentOut
from app.services.events import emit

router = APIRouter(prefix="/incidents", tags=["incidents"])


def _event_dict(e: AgentEvent) -> dict:
    return {
        "id": e.id,
        "agent": e.agent,
        "type": e.event_type,
        "payload": e.payload,
        "at": e.created_at.isoformat(),
    }


async def _get_or_404(session: AsyncSession, incident_id: uuid.UUID) -> Incident:
    incident = await session.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident


@router.get("", response_model=list[IncidentOut])
async def list_incidents(session: AsyncSession = Depends(get_session)):
    rows = await session.execute(select(Incident).order_by(Incident.opened_at.desc()).limit(50))
    return rows.scalars().all()


@router.get("/{incident_id}", response_model=IncidentOut)
async def get_incident(incident_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await _get_or_404(session, incident_id)


@router.get("/{incident_id}/events")
async def get_events(incident_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(AgentEvent).where(AgentEvent.incident_id == incident_id).order_by(AgentEvent.id)
    )
    return [_event_dict(e) for e in rows.scalars().all()]


@router.get("/{incident_id}/stream")
async def stream_events(incident_id: uuid.UUID, request: Request):
    """Server-sent events. Polls the events table, simple and reliable."""

    async def generate():
        last_id = 0
        while True:
            if await request.is_disconnected():
                break
            async with SessionLocal() as session:
                rows = await session.execute(
                    select(AgentEvent)
                    .where(AgentEvent.incident_id == incident_id, AgentEvent.id > last_id)
                    .order_by(AgentEvent.id)
                )
                for event in rows.scalars().all():
                    last_id = event.id
                    yield f"data: {json.dumps(_event_dict(event))}\n\n"
            await asyncio.sleep(0.7)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{incident_id}/decision")
async def decide(incident_id: uuid.UUID, body: DecisionIn, session: AsyncSession = Depends(get_session)):
    incident = await _get_or_404(session, incident_id)
    if incident.status != "awaiting_approval" or not incident.proposed_action:
        raise HTTPException(status_code=409, detail=f"incident is {incident.status}, not awaiting approval")

    action = incident.proposed_action
    session.add(
        Approval(
            incident_id=incident.id,
            proposed_action=action,
            decision=body.decision,
            decided_by=body.decided_by,
            comment=body.comment,
        )
    )
    # Move out of awaiting_approval right away so a double click cannot approve twice.
    incident.status = "executing" if body.decision == "approve" else "investigating"
    await session.commit()

    decision = {"decision": body.decision, "comment": body.comment, "decided_by": body.decided_by}
    if body.decision == "approve":
        # The docker MCP server refuses to act without this token.
        message = approval_message(str(incident.id), action["type"], action["target"])
        decision["approval_token"] = sign(settings.approval_secret, message)

    await emit(incident.id, "human", "decision", f"{body.decided_by} {body.decision}d the proposed action", comment=body.comment)
    await publish({"type": "resume", "incident_id": str(incident.id), "decision": decision})
    return {"ok": True}


@router.get("/{incident_id}/postmortem", response_class=PlainTextResponse)
async def get_postmortem(incident_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    row = (
        await session.execute(select(Postmortem).where(Postmortem.incident_id == incident_id))
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="no postmortem yet")
    return row.markdown
