import json
import os
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row


def connect():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def parse_ts(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def log_window(end: str, minutes: int):
    """Logs are stamped within their minute, so the window runs one minute past `end`."""
    e = parse_ts(end)
    return e - timedelta(minutes=minutes), e + timedelta(minutes=1)


def metric_window(end: str, minutes: int):
    e = parse_ts(end)
    return e - timedelta(minutes=minutes), e


def dumps(data) -> str:
    return json.dumps(data, default=str)
