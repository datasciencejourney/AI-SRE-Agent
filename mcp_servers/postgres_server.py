from mcp.server.fastmcp import FastMCP

from mcp_servers.common import connect, dumps, log_window, metric_window
from mcp_servers.sqlguard import validate_sql

mcp = FastMCP("postgres")


@mcp.tool()
def readonly_query(sql: str) -> str:
    """Run one read-only SELECT. Writes are rejected, queries time out after 3 seconds, 50 rows max."""
    safe = validate_sql(sql)
    with connect() as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = 3000")
        rows = conn.execute(f"SELECT * FROM ({safe}) AS q LIMIT 50").fetchall()
    return dumps(rows)


@mcp.tool()
def get_slow_queries(service: str, end: str, minutes: int = 30) -> str:
    """Slow query warnings found in a service's logs, grouped by statement."""
    lo, hi = log_window(end, minutes)
    with connect() as conn:
        rows = conn.execute(
            """SELECT regexp_replace(message, '[0-9]+', 'N', 'g') AS message, count(*)::int AS count
               FROM log_events
               WHERE service = %s AND message ILIKE '%%slow query%%' AND ts >= %s AND ts <= %s
               GROUP BY 1 ORDER BY count DESC LIMIT 5""",
            (service, lo, hi),
        ).fetchall()
    return dumps(rows)


@mcp.tool()
def get_connections(service: str, end: str) -> str:
    """Database connections in use now, compared with the healthy baseline."""
    lo, hi = metric_window(end, 60)
    with connect() as conn:
        rows = conn.execute(
            """SELECT ts, value FROM metric_points
               WHERE service = %s AND name = 'db_connections_in_use' AND ts >= %s AND ts <= %s ORDER BY ts""",
            (service, lo, hi),
        ).fetchall()
    if not rows:
        return dumps({"latest": None, "baseline": None})
    early = [r["value"] for r in rows[:15]]
    return dumps({"latest": rows[-1]["value"], "baseline": sum(early) / len(early)})


if __name__ == "__main__":
    mcp.run()
