"""Load a generated scenario into Postgres. Sync code, so call it with asyncio.to_thread from the API."""
import psycopg
from psycopg.types.json import Jsonb

from victim.generate import generate


def load_scenario(name: str, dsn: str, seed: int = 7) -> dict:
    data = generate(name, seed=seed)
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE log_events, metric_points, deploy_events RESTART IDENTITY")
        cur.executemany(
            "INSERT INTO log_events (service, level, message, ts, fields) VALUES (%s,%s,%s,%s,%s)",
            [(r["service"], r["level"], r["message"], r["ts"], Jsonb(r["fields"])) for r in data["logs"]],
        )
        cur.executemany(
            "INSERT INTO metric_points (service, name, value, ts) VALUES (%s,%s,%s,%s)",
            [(r["service"], r["name"], r["value"], r["ts"]) for r in data["metrics"]],
        )
        cur.executemany(
            "INSERT INTO deploy_events (sha, service, author, message, ts, files) VALUES (%s,%s,%s,%s,%s,%s)",
            [(r["sha"], r["service"], r["author"], r["message"], r["ts"], Jsonb(r["files"])) for r in data["deploys"]],
        )
        cur.execute(
            "INSERT INTO scenario_runs (scenario, expected) VALUES (%s,%s)",
            (name, Jsonb(data["expected"])),
        )
    return data
