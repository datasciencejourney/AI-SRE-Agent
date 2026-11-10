"""The only server that can change anything. Every write needs a valid approval token."""
import os

from mcp.server.fastmcp import FastMCP

from app.core.tokens import approval_message, verify
from mcp_servers.common import connect, dumps
from victim.generate import BASELINE, SERVICES

mcp = FastMCP("docker")
ALLOWED = set(SERVICES)


def _check(tool: str, name: str, incident_id: str, token: str) -> None:
    if name not in ALLOWED:
        raise ValueError(f"service '{name}' is not on the allowlist")
    secret = os.environ.get("APPROVAL_SECRET", "dev-approval-secret")
    if not verify(secret, approval_message(incident_id, tool, name), token):
        raise PermissionError("missing or invalid approval token")


def _heal(note: str) -> None:
    """Level 1 has no real containers, so 'fixing' means writing healthy data and a log line."""
    with connect() as conn:
        for service in SERVICES:
            for metric, value in BASELINE.items():
                conn.execute(
                    "INSERT INTO metric_points (service, name, value, ts) VALUES (%s, %s, %s, clock_timestamp())",
                    (service, metric, value),
                )
        conn.execute(
            "INSERT INTO log_events (service, level, message, ts, fields) VALUES ('payments', 'INFO', %s, clock_timestamp(), '{}')",
            (note,),
        )


@mcp.tool()
def list_containers() -> str:
    """Services this server is allowed to touch."""
    return dumps([{"name": s, "status": "running"} for s in sorted(ALLOWED)])


@mcp.tool()
def restart_container(name: str, incident_id: str, approval_token: str) -> str:
    """Restart a service. Needs an approval token for this exact incident and service."""
    _check("restart_container", name, incident_id, approval_token)
    _heal(f"{name} restarted by SRE agent (incident {incident_id[:8]})")
    return dumps({"ok": True, "action": "restart_container", "target": name})


@mcp.tool()
def rollback_service(name: str, version: str, incident_id: str, approval_token: str) -> str:
    """Roll a service back to an earlier version. Needs an approval token."""
    _check("rollback_service", name, incident_id, approval_token)
    _heal(f"{name} rolled back to {version} by SRE agent (incident {incident_id[:8]})")
    return dumps({"ok": True, "action": "rollback_service", "target": name, "version": version})


if __name__ == "__main__":
    mcp.run()
