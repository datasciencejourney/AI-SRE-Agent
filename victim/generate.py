"""Level 1 data generator.

Builds fake-but-realistic logs, metrics and deploy history for a failure scenario.
Everything is deterministic for a given (scenario, now, seed), which makes tests stable.

The agents only ever see: alert, logs, metrics, deploys.
The `expected` answer key is kept separate and is used only by tests and the evaluator.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone

SERVICES = ["payments", "orders", "users"]
HISTORY_MINUTES = 60
FAULT_MINUTES_AGO = 10

BASELINE = {
    "request_rate": 50.0,
    "error_rate": 0.01,
    "p95_latency_ms": 120.0,
    "cpu_pct": 35.0,
    "memory_mb": 300.0,
    "db_connections_in_use": 6.0,
}

HEALTHY_LOGS = {
    "payments": [
        "POST /pay 200 duration_ms={ms}",
        "payment captured amount={amt} currency=INR",
        "db query ok duration_ms={ms}",
    ],
    "orders": [
        "GET /orders 200 duration_ms={ms}",
        "order created id={id}",
        "inventory check ok duration_ms={ms}",
    ],
    "users": [
        "GET /users/me 200 duration_ms={ms}",
        "session refreshed user_id={id}",
        "login ok user_id={id}",
    ],
}

# Harmless history so the "latest deploy" is not always the culprit.
BASELINE_DEPLOYS = [
    {"service": s, "min_ago": days * 1440, "author": "dev-team", "message": msg,
     "files": [{"path": "README.md", "patch": "+ minor wording fix"}]}
    for s in SERVICES
    for days, msg in [(2, "update dependencies"), (5, "fix typo in error message")]
]

# effects: metric -> ("step", value) or ("ramp", (start_value, end_value))
SCENARIOS: dict[str, dict] = {
    "bad_config": {
        "description": "A release shrinks the DB connection pool from 20 to 2.",
        "alert": {"alert_name": "HighErrorRate", "service": "payments",
                  "summary": "payments error rate above 30% for 5 minutes"},
        "faults": [{
            "service": "payments", "errors_per_min": 14, "level": "ERROR",
            "messages": [
                "DB connection pool timeout after 5000ms (pool_size=2)",
                "POST /pay 500 duration_ms={ms} error=pool timeout",
                "QueuePool limit of size 2 overflow 0 reached, connection timed out",
            ],
            "effects": {"error_rate": ("step", 0.41), "p95_latency_ms": ("step", 4800),
                        "db_connections_in_use": ("step", 2)},
        }],
        "deploys": [{
            "service": "payments", "min_ago": 11, "author": "sam",
            "message": "tune db pool for cost savings",
            "files": [{"path": "config/payments.env",
                       "patch": "- DB_POOL_SIZE=20\n+ DB_POOL_SIZE=2"}],
        }],
        "expected": {"category": "config_change", "service": "payments",
                     "keywords": ["DB_POOL_SIZE", "pool"], "action": "rollback_service"},
    },
    "slow_query": {
        "description": "A new query without an index makes payments slow.",
        "alert": {"alert_name": "HighLatency", "service": "payments",
                  "summary": "payments p95 latency above 3s for 5 minutes"},
        "faults": [{
            "service": "payments", "errors_per_min": 8, "level": "WARN",
            "messages": [
                "slow query 5123ms: SELECT * FROM payments WHERE customer_id = $1",
                "slow query 4876ms: SELECT * FROM payments WHERE customer_id = $1",
                "POST /pay 200 duration_ms={ms} (slow)",
            ],
            "effects": {"p95_latency_ms": ("step", 5000), "error_rate": ("step", 0.04),
                        "db_connections_in_use": ("step", 14)},
        }],
        "deploys": [{
            "service": "payments", "min_ago": 12, "author": "priya",
            "message": "add customer lookup to payment flow",
            "files": [{"path": "app/payments.py",
                       "patch": "+ rows = db.execute('SELECT * FROM payments WHERE customer_id = %s', cid)"},
                      {"path": "migrations/0042_add_customer_id.sql",
                       "patch": "+ ALTER TABLE payments ADD COLUMN customer_id BIGINT;  -- no index"}],
        }],
        "expected": {"category": "slow_query", "service": "payments",
                     "keywords": ["customer_id", "index"], "action": "rollback_service"},
    },
    "memory_leak": {
        "description": "An unbounded in-memory cache slowly eats memory.",
        "alert": {"alert_name": "HighMemory", "service": "payments",
                  "summary": "payments memory above 1.2GB and rising"},
        "faults": [{
            "service": "payments", "start_min_ago": 45, "errors_per_min": 3, "level": "WARN",
            "messages": [
                "GC overhead high: 38% of time in garbage collection",
                "response cache size=issued entries growing, no eviction",
                "memory usage above 80% of container limit",
            ],
            "effects": {"memory_mb": ("ramp", (300, 1800)), "p95_latency_ms": ("ramp", (120, 900))},
        }],
        "deploys": [{
            "service": "payments", "min_ago": 180, "author": "lee",
            "message": "cache payment responses in memory",
            "files": [{"path": "app/cache.py",
                       "patch": "+ CACHE = {}  # keyed by request id\n+ CACHE[req_id] = response  # never evicted"}],
        }],
        "expected": {"category": "memory_leak", "service": "payments",
                     "keywords": ["cache", "memory"], "action": "restart_container"},
    },
    "crash_loop": {
        "description": "A renamed env var makes the container exit on startup.",
        "alert": {"alert_name": "ServiceDown", "service": "payments",
                  "summary": "payments has had no successful requests for 5 minutes"},
        "faults": [{
            "service": "payments", "errors_per_min": 6, "level": "ERROR", "suppress_healthy": True,
            "messages": [
                "KeyError: 'PAYMENT_API_KEY' - environment variable not set",
                "container exited code=1, restarting (backoff 10s)",
                "startup failed: missing required configuration",
            ],
            "effects": {"request_rate": ("step", 0), "error_rate": ("step", 1.0),
                        "cpu_pct": ("step", 3), "memory_mb": ("step", 40)},
        }],
        "deploys": [{
            "service": "payments", "min_ago": 11, "author": "ravi",
            "message": "rename env var PAYMENT_KEY to PAYMENT_API_KEY",
            "files": [{"path": "app/settings.py",
                       "patch": "- KEY = os.environ['PAYMENT_KEY']\n+ KEY = os.environ['PAYMENT_API_KEY']"},
                      {"path": "docker-compose.yml", "patch": "  (env var not renamed here)"}],
        }],
        "expected": {"category": "crash_loop", "service": "payments",
                     "keywords": ["PAYMENT_API_KEY", "env"], "action": "rollback_service"},
    },
    "dependency_down": {
        "description": "orders is down; payments fails because it calls orders.",
        "alert": {"alert_name": "HighErrorRate", "service": "payments",
                  "summary": "payments error rate above 30% for 5 minutes"},
        "faults": [
            {"service": "orders", "errors_per_min": 5, "level": "ERROR", "suppress_healthy": True,
             "messages": ["health check failed: process not responding",
                          "worker killed by OOM reaper, not restarted"],
             "effects": {"request_rate": ("step", 0), "error_rate": ("step", 1.0)}},
            {"service": "payments", "errors_per_min": 12, "level": "ERROR",
             "messages": ["upstream orders unreachable: connection refused (orders:8000)",
                          "POST /pay 502 duration_ms={ms} error=upstream orders failed"],
             "effects": {"error_rate": ("step", 0.38)}},
        ],
        "deploys": [],
        "expected": {"category": "dependency_down", "service": "orders",
                     "keywords": ["orders", "connection refused"], "action": "restart_container"},
    },
    "traffic_spike": {
        "description": "A sudden 10x traffic burst. No bad deploy at all.",
        "alert": {"alert_name": "HighLatency", "service": "payments",
                  "summary": "payments p95 latency above 2s, cpu above 90%"},
        "faults": [{
            "service": "payments", "errors_per_min": 10, "level": "WARN",
            "messages": ["request queue full, shedding load",
                         "POST /pay 503 duration_ms={ms} error=overloaded",
                         "worker pool saturated: 32/32 busy"],
            "effects": {"request_rate": ("step", 600), "cpu_pct": ("step", 96),
                        "p95_latency_ms": ("step", 3000), "error_rate": ("step", 0.22)},
        }],
        "deploys": [{
            "service": "payments", "min_ago": 40, "author": "dev-team",
            "message": "bump logging format",
            "files": [{"path": "app/logging.py", "patch": "+ log_format = 'json'"}],
        }],
        "expected": {"category": "traffic_spike", "service": "payments",
                     "keywords": ["traffic", "request_rate"], "action": "none"},
    },
    "false_alarm": {
        "description": "A harmless one-minute blip that already recovered.",
        "alert": {"alert_name": "HighErrorRate", "service": "payments",
                  "summary": "payments error rate briefly above 10%"},
        "faults": [{
            "service": "payments", "start_min_ago": 3, "end_min_ago": 2, "errors_per_min": 3,
            "level": "ERROR",
            "messages": ["POST /pay 500 duration_ms={ms} error=transient network reset"],
            "effects": {"error_rate": ("step", 0.12)},
        }],
        "deploys": [],
        "expected": {"category": "false_alarm", "service": "payments",
                     "keywords": ["transient", "recovered"], "action": "none"},
    },
}


def _short_sha(seed: int, service: str, message: str) -> str:
    return hashlib.sha1(f"{seed}-{service}-{message}".encode()).hexdigest()[:7]


def _fault_for(faults: list[dict], service: str, m: int) -> dict | None:
    """Return the active fault for `service` at `m` minutes ago, if any."""
    for f in faults:
        if f["service"] == service and f.get("start_min_ago", FAULT_MINUTES_AGO) >= m >= f.get("end_min_ago", 0):
            return f
    return None


def _effect_value(effect: tuple, progress: float) -> float:
    kind, value = effect
    if kind == "step":
        return float(value)
    start, end = value
    return start + (end - start) * progress


def list_scenarios() -> list[str]:
    return list(SCENARIOS)


def generate(name: str, now: datetime | None = None, seed: int = 7) -> dict:
    if name not in SCENARIOS:
        raise KeyError(f"unknown scenario '{name}'. Options: {', '.join(SCENARIOS)}")
    spec = SCENARIOS[name]
    rng = random.Random(f"{name}-{seed}")
    now = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)

    logs: list[dict] = []
    metrics: list[dict] = []

    for m in range(HISTORY_MINUTES, -1, -1):
        minute = now - timedelta(minutes=m)
        for service in SERVICES:
            fault = _fault_for(spec["faults"], service, m)
            progress = 0.0
            if fault:
                start = fault.get("start_min_ago", FAULT_MINUTES_AGO)
                end = fault.get("end_min_ago", 0)
                progress = (start - m) / max(start - end, 1)

            # metrics
            for metric, base in BASELINE.items():
                if fault and metric in fault["effects"]:
                    value = _effect_value(fault["effects"][metric], progress)
                    value *= 1 + rng.gauss(0, 0.02)
                else:
                    value = base * (1 + rng.gauss(0, 0.05))
                metrics.append({"service": service, "name": metric,
                                "value": round(max(value, 0.0), 3), "ts": minute})

            # healthy logs
            if not (fault and fault.get("suppress_healthy")):
                for _ in range(4):
                    text = rng.choice(HEALTHY_LOGS[service]).format(
                        ms=rng.randint(40, 180), amt=rng.randint(100, 5000), id=rng.randint(1000, 9999))
                    logs.append({"service": service, "level": "INFO", "message": text,
                                 "ts": minute + timedelta(seconds=rng.randint(0, 59)),
                                 "fields": {"host": f"{service}-1"}})

            # fault logs
            if fault:
                for _ in range(fault["errors_per_min"]):
                    text = rng.choice(fault["messages"]).format(ms=rng.randint(3000, 9000))
                    logs.append({"service": service, "level": fault["level"], "message": text,
                                 "ts": minute + timedelta(seconds=rng.randint(0, 59)),
                                 "fields": {"host": f"{service}-1"}})

    deploys = []
    for d in BASELINE_DEPLOYS + spec["deploys"]:
        deploys.append({"sha": _short_sha(seed, d["service"], d["message"]), "service": d["service"],
                        "author": d["author"], "message": d["message"],
                        "ts": now - timedelta(minutes=d["min_ago"]), "files": d["files"]})
    deploys.sort(key=lambda d: d["ts"])
    logs.sort(key=lambda l: l["ts"])

    a = spec["alert"]
    alert = {
        "alert_name": a["alert_name"], "service": a["service"], "status": "firing",
        "fired_at": now.isoformat(), "summary": a["summary"], "labels": {"env": "dev"},
    }
    return {"scenario": name, "alert": alert, "logs": logs, "metrics": metrics,
            "deploys": deploys, "expected": spec["expected"]}
