from datetime import timedelta

from mcp.server.fastmcp import FastMCP

from mcp_servers.common import connect, dumps, metric_window, parse_ts

mcp = FastMCP("metrics")


@mcp.tool()
def get_metric(service: str, name: str, end: str, minutes: int = 15) -> str:
    """A metric as a list of {ts, value}, oldest first."""
    lo, hi = metric_window(end, minutes)
    with connect() as conn:
        rows = conn.execute(
            """SELECT ts, value FROM metric_points
               WHERE service = %s AND name = %s AND ts >= %s AND ts <= %s
               ORDER BY ts LIMIT 200""",
            (service, name, lo, hi),
        ).fetchall()
    return dumps(rows)


@mcp.tool()
def compare_windows(service: str, name: str, end: str, recent_minutes: int = 5, baseline_start: int = 60, baseline_end: int = 45) -> str:
    """Compare the last few minutes with an older healthy baseline window (minutes before `end`)."""
    e = parse_ts(end)
    with connect() as conn:
        rows = conn.execute(
            """SELECT ts, value FROM metric_points
               WHERE service = %s AND name = %s AND ts >= %s AND ts <= %s ORDER BY ts""",
            (service, name, e - timedelta(minutes=baseline_start), e),
        ).fetchall()
    base = [r["value"] for r in rows if e - timedelta(minutes=baseline_start) <= r["ts"] <= e - timedelta(minutes=baseline_end)]
    recent = [r["value"] for r in rows if r["ts"] >= e - timedelta(minutes=recent_minutes)]
    if not rows or not recent:
        return dumps({"baseline_avg": None, "recent_avg": None, "latest": None, "max_recent": None})
    return dumps(
        {
            "baseline_avg": sum(base) / len(base) if base else None,
            "recent_avg": sum(recent) / len(recent),
            "latest": rows[-1]["value"],
            "max_recent": max(recent),
        }
    )


if __name__ == "__main__":
    mcp.run()
