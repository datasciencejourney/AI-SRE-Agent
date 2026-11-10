"""Calls tools on the MCP servers. Each call starts the server as a subprocess over stdio."""
import json
import os
import sys
import time
import uuid
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.db.models import ToolCall
from app.db.session import SessionLocal

ROOT = Path(__file__).resolve().parents[2]
SERVERS = {
    "logs": "mcp_servers.logs_server",
    "metrics": "mcp_servers.metrics_server",
    "github": "mcp_servers.github_server",
    "postgres": "mcp_servers.postgres_server",
    "docker": "mcp_servers.docker_server",
}
SECRET_ARGS = {"approval_token"}


class ToolError(Exception):
    pass


async def _audit(incident_id, agent, server, tool, args, summary, ms, ok):
    try:
        async with SessionLocal() as session:
            session.add(
                ToolCall(
                    incident_id=uuid.UUID(incident_id) if incident_id else None,
                    agent=agent,
                    server=server,
                    tool=tool,
                    args={k: ("***" if k in SECRET_ARGS else v) for k, v in args.items()},
                    result_summary=summary,
                    duration_ms=ms,
                    ok=ok,
                )
            )
            await session.commit()
    except Exception:
        pass  # auditing must never break an investigation


async def call_tool(server: str, tool: str, args: dict, incident_id: str | None = None, agent: str = ""):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", SERVERS[server]],
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        cwd=str(ROOT),
    )
    started = time.perf_counter()
    ok, summary = True, ""
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, args)
        text = result.content[0].text if result.content else "null"
        if result.isError:
            raise ToolError(text)
        summary = text[:300]
        return json.loads(text)
    except Exception as e:
        root = e
        while isinstance(root, BaseExceptionGroup) and root.exceptions:
            root = root.exceptions[0]  # unwrap the TaskGroup to find the real cause
        ok, summary = False, f"{type(root).__name__}: {root}"[:300]
        raise ToolError(summary) from e
    finally:
        ms = int((time.perf_counter() - started) * 1000)
        await _audit(incident_id, agent, server, tool, args, summary, ms, ok)
