"""Reads the alert stream and drives the LangGraph workflow.

Run with: python -m app.worker
"""
import asyncio
import json
import logging
import os
import uuid

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from sqlalchemy import select

from app.core.config import settings
from app.db.models import Alert
from app.db.session import SessionLocal, init_db
from app.orchestrator.graph import build_graph
from app.queue.stream import dead_letter, ensure_group, get_redis
from app.rag.store import seed_runbooks
from app.services.events import emit
from app.services.incidents import get_incident, update_incident
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")


def thread_config(incident_id: str) -> dict:
    # One LangGraph thread per incident, so every incident has its own saved state.
    return {"configurable": {"thread_id": incident_id}, "recursion_limit": 50}


async def start_incident(graph, incident_id: str) -> None:
    incident = await get_incident(incident_id)
    if incident is None:
        log.warning("incident %s not found", incident_id)
        return

    cfg = thread_config(incident_id)
    snapshot = await graph.aget_state(cfg)
    if snapshot and snapshot.next and incident.status == "investigating":
        log.info("resuming unfinished incident %s", incident_id)  # worker crashed earlier
        await graph.ainvoke(None, cfg)
        return
    if incident.status != "open":
        log.info("skipping incident %s (status %s)", incident_id, incident.status)
        return

    async with SessionLocal() as session:
        alert = (
            await session.execute(select(Alert).where(Alert.incident_id == uuid.UUID(incident_id)).order_by(Alert.received_at))
        ).scalars().first()
    state = {"incident_id": incident_id, "alert": alert.payload, "findings": [], "loop_count": 0, "attempt": 0}
    await graph.ainvoke(state, cfg)


async def resume_incident(graph, incident_id: str, decision: dict) -> None:
    await graph.ainvoke(Command(resume=decision), thread_config(incident_id))


async def handle(graph, data: dict) -> None:
    if data["type"] == "alert":
        await start_incident(graph, data["incident_id"])
    elif data["type"] == "resume":
        await resume_incident(graph, data["incident_id"], data["decision"])
    else:
        log.warning("unknown message type %s", data["type"])


async def main() -> None:
    await init_db()
    await seed_runbooks()
    await ensure_group()
    r = get_redis()
    consumer = os.getenv("WORKER_NAME", "worker-1")

    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as saver:
        await saver.setup()
        graph = build_graph(saver)
        log.info("worker ready (llm=%s)", "on" if settings.anthropic_api_key else "off, using rule engine")

        backlog = True  # first drain messages this consumer read but never acknowledged
        while True:
            try:
                resp = await r.xreadgroup(
                    settings.consumer_group, consumer,
                    {settings.alert_stream: "0" if backlog else ">"},
                    count=1, block=None if backlog else 5000,
                )
            except (RedisConnectionError, RedisTimeoutError):
                continue
            
            entries = resp[0][1] if resp else []
            if backlog and not entries:
                backlog = False
                continue

            for msg_id, fields in entries:
                data = json.loads(fields["data"])
                try:
                    log.info("handling %s", data)
                    await handle(graph, data)
                except Exception as e:
                    log.exception("failed to handle %s", data)
                    incident_id = data.get("incident_id")
                    if incident_id:
                        await emit(incident_id, "worker", "error", f"Processing failed: {e}")
                        await update_incident(incident_id, status="escalated")
                    await dead_letter(data, repr(e))
                finally:
                    await r.xack(settings.alert_stream, settings.consumer_group, msg_id)


if __name__ == "__main__":
    asyncio.run(main())
