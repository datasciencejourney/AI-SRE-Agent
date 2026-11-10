from mcp.server.fastmcp import FastMCP

from mcp_servers.common import connect, dumps, log_window, parse_ts

mcp = FastMCP("logs")


@mcp.tool()
def search_logs(service: str, end: str, minutes: int = 15, query: str = "", levels: str = "ERROR,WARN", limit: int = 20) -> str:
    """Search recent log lines of one service. `end` is an ISO timestamp (the alert time)."""
    lo, hi = log_window(end, minutes)
    wanted = [x.strip().upper() for x in levels.split(",") if x.strip()]
    with connect() as conn:
        rows = conn.execute(
            """SELECT ts, level, message FROM log_events
               WHERE service = %s AND level = ANY(%s) AND ts >= %s AND ts <= %s AND message ILIKE %s
               ORDER BY ts DESC LIMIT %s""",
            (service, wanted, lo, hi, f"%{query}%", min(limit, 50)),
        ).fetchall()
    return dumps(rows)


@mcp.tool()
def top_error_messages(service: str, end: str, minutes: int = 15) -> str:
    """Most common error/warning messages, with numbers replaced by N so similar lines group together."""
    lo, hi = log_window(end, minutes)
    with connect() as conn:
        rows = conn.execute(
            """SELECT regexp_replace(message, '[0-9]+', 'N', 'g') AS message, count(*)::int AS count
               FROM log_events
               WHERE service = %s AND level IN ('ERROR','WARN') AND ts >= %s AND ts <= %s
               GROUP BY 1 ORDER BY count DESC LIMIT 8""",
            (service, lo, hi),
        ).fetchall()
    return dumps(rows)


@mcp.tool()
def count_errors(service: str, end: str, minutes: int = 15) -> str:
    """Error and warning counts, how many distinct minutes had problems, and how long ago the last one was."""
    lo, hi = log_window(end, minutes)
    with connect() as conn:
        row = conn.execute(
            """SELECT count(*) FILTER (WHERE level = 'ERROR')::int AS errors,
                      count(*) FILTER (WHERE level = 'WARN')::int AS warns,
                      count(DISTINCT date_trunc('minute', ts))::int AS error_minutes,
                      max(ts) AS last_ts
               FROM log_events
               WHERE service = %s AND level IN ('ERROR','WARN') AND ts >= %s AND ts <= %s""",
            (service, lo, hi),
        ).fetchone()
    age = None
    if row["last_ts"] is not None:
        age = max(0.0, (parse_ts(end) - row["last_ts"]).total_seconds() / 60)
    return dumps(
        {"errors": row["errors"], "warns": row["warns"], "error_minutes": row["error_minutes"], "last_error_age_min": age}
    )


@mcp.tool()
def services_with_errors(end: str, minutes: int = 15) -> str:
    """Which services logged errors or warnings recently, and how many."""
    lo, hi = log_window(end, minutes)
    with connect() as conn:
        rows = conn.execute(
            """SELECT service, count(*)::int AS errors FROM log_events
               WHERE level IN ('ERROR','WARN') AND ts >= %s AND ts <= %s
               GROUP BY service ORDER BY errors DESC""",
            (lo, hi),
        ).fetchall()
    return dumps(rows)


@mcp.tool()
def first_error_time(service: str, end: str, minutes: int = 60) -> str:
    """When did the first error or warning of this service appear in the window."""
    lo, hi = log_window(end, minutes)
    with connect() as conn:
        row = conn.execute(
            """SELECT min(ts) AS ts FROM log_events
               WHERE service = %s AND level IN ('ERROR','WARN') AND ts >= %s AND ts <= %s""",
            (service, lo, hi),
        ).fetchone()
    return dumps({"ts": row["ts"]})


if __name__ == "__main__":
    mcp.run()
