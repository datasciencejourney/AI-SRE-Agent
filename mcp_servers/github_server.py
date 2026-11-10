from datetime import timedelta

from mcp.server.fastmcp import FastMCP

from mcp_servers.common import connect, dumps, parse_ts

mcp = FastMCP("github")


@mcp.tool()
def list_recent_deploys(service: str, end: str, hours: int = 6) -> str:
    """Deploys of a service in the last N hours before `end`, oldest first."""
    e = parse_ts(end)
    with connect() as conn:
        rows = conn.execute(
            """SELECT sha, author, message, ts, files FROM deploy_events
               WHERE service = %s AND ts <= %s AND ts >= %s ORDER BY ts""",
            (service, e + timedelta(minutes=1), e - timedelta(hours=hours)),
        ).fetchall()
    return dumps(rows)


@mcp.tool()
def get_commit_diff(sha: str) -> str:
    """Files changed by one deploy, with their patches."""
    with connect() as conn:
        row = conn.execute("SELECT sha, message, author, ts, files FROM deploy_events WHERE sha = %s LIMIT 1", (sha,)).fetchone()
    return dumps(row)


if __name__ == "__main__":
    mcp.run()
