"""What each investigator does with the tool results.

Every function here is plain Python. The investigators receive a `call` coroutine,
call(server, tool, **args), so in production it talks to MCP servers and in
tests it can be faked. That is how the scenarios are tested without a database.
"""
import re
from datetime import datetime, timedelta, timezone

POOL = re.compile(r"connection pool|pool timeout|queuepool", re.I)
SLOW = re.compile(r"slow query", re.I)
CRASH = re.compile(r"keyerror|exited code|restarting|startup failed", re.I)
OVERLOAD = re.compile(r"queue full|shedding|saturated|overloaded", re.I)
MEMORY = re.compile(r"gc overhead|memory usage|cache size", re.I)
UPSTREAM = re.compile(r"upstream (\w+) (?:unreachable|failed)", re.I)

CONFIG_FILE = re.compile(r"config/|\.env\b|pool_size", re.I)


def parse_ts(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def make_finding(agent: str, signals, evidence, data, summary: str) -> dict:
    return {"agent": agent, "signals": list(signals), "evidence": list(evidence), "data": data, "summary": summary}


# ---------------------------------------------------------------- logs
def log_signals(top, stats, other_errors, alert_service):
    signals, evidence, data = [], [], {}
    patterns = [
        ("pool_errors", POOL),
        ("slow_queries", SLOW),
        ("crash_logs", CRASH),
        ("overload_logs", OVERLOAD),
        ("memory_logs", MEMORY),
    ]
    for row in top:
        msg, n = row["message"], row["count"]
        for name, rx in patterns:
            if rx.search(msg) and name not in signals:
                signals.append(name)
                evidence.append(f'{n}x log: "{msg[:90]}"')
        m = UPSTREAM.search(msg)
        if m and m.group(1).lower() != alert_service and "upstream_unreachable" not in signals:
            dep = m.group(1).lower()
            data["dependency"] = dep
            signals.append("upstream_unreachable")
            evidence.append(f"{n}x log says upstream '{dep}' failed")
            if other_errors.get(dep, 0) > 0:
                signals.append("dependency_failing")
                evidence.append(f"'{dep}' is also logging errors ({other_errors[dep]} lines)")

    age = stats.get("last_error_age_min")
    if stats.get("error_minutes", 0) <= 2 and age is not None and age >= 1.0:
        signals.append("transient_only")
        evidence.append(f"errors lasted {stats['error_minutes']} minute(s) and stopped {age:.0f} min ago")
    return signals, evidence, data


async def logs_investigation(call, svc, end, minutes):
    top = await call("logs", "top_error_messages", service=svc, end=end, minutes=minutes)
    stats = await call("logs", "count_errors", service=svc, end=end, minutes=minutes)
    others = await call("logs", "services_with_errors", end=end, minutes=minutes)
    other_errors = {r["service"]: r["errors"] for r in others if r["service"] != svc}
    signals, evidence, data = log_signals(top, stats, other_errors, svc)
    total = stats.get("errors", 0) + stats.get("warns", 0)
    summary = f"{total} error/warn lines in {svc} over {minutes} min; top: " + (top[0]["message"][:70] if top else "none")
    return make_finding("logs", signals, evidence, data, summary)


# ---------------------------------------------------------------- metrics
METRICS = ["error_rate", "p95_latency_ms", "request_rate", "cpu_pct", "memory_mb"]


def metric_signals(m):
    signals, evidence = [], []

    def stat(name, key):
        v = (m.get(name) or {}).get(key)
        return 0.0 if v is None else float(v)

    err_avg, err_now = stat("error_rate", "recent_avg"), stat("error_rate", "latest")
    if err_avg > 0.1:
        signals.append("error_spike")
        evidence.append(f"error rate averaged {err_avg:.0%} over the last 5 min")
    if (m.get("error_rate") or {}).get("latest") is not None and err_now < 0.03:
        signals.append("recovered")
        evidence.append(f"error rate is back to {err_now:.1%} now")

    lat, lat_base = stat("p95_latency_ms", "latest"), max(stat("p95_latency_ms", "baseline_avg"), 1.0)
    if lat > 5 * lat_base:
        signals.append("latency_spike")
        evidence.append(f"p95 latency {lat:.0f}ms vs {lat_base:.0f}ms normally")

    req, req_base = stat("request_rate", "latest"), stat("request_rate", "baseline_avg")
    if req_base > 0 and req > 3 * req_base:
        signals.append("request_spike")
        evidence.append(f"request rate {req:.0f}/s vs {req_base:.0f}/s normally")
    if req_base > 10 and req < 1:
        signals.append("requests_zero")
        evidence.append("no requests are being served at all")

    if stat("cpu_pct", "latest") > 85:
        signals.append("cpu_high")
        evidence.append(f"cpu at {stat('cpu_pct', 'latest'):.0f}%")

    mem, mem_base = stat("memory_mb", "latest"), stat("memory_mb", "baseline_avg")
    if mem_base > 0 and mem > 2 * mem_base:
        signals.append("memory_ramp")
        evidence.append(f"memory {mem:.0f}MB vs {mem_base:.0f}MB normally")
    return signals, evidence


async def metrics_investigation(call, svc, end, minutes):
    stats = {}
    for name in METRICS:
        stats[name] = await call(
            "metrics", "compare_windows", service=svc, name=name, end=end,
            recent_minutes=5, baseline_start=60, baseline_end=45,
        )
    signals, evidence = metric_signals(stats)
    summary = f"{len(signals)} metric signal(s) for {svc}: " + (", ".join(signals) if signals else "all normal")
    return make_finding("metrics", signals, evidence, {}, summary)


# ---------------------------------------------------------------- deploys
def _deploy_text(d) -> str:
    parts = [d["message"]] + [f"{f['path']} {f['patch']}" for f in d.get("files", [])]
    return " ".join(parts).lower()


def deploy_signals(deploys, fault_start):
    """deploys: recent deploys (hours, not days). fault_start: datetime or None."""
    signals, evidence, data = [], [], {}
    ordered = sorted(deploys, key=lambda d: parse_ts(d["ts"]))
    culprit = None

    if fault_start is not None:
        for d in reversed(ordered):
            gap = (fault_start - parse_ts(d["ts"])).total_seconds() / 60
            if -2 <= gap <= 20:  # shipped shortly before the trouble began
                culprit = d
                signals.append("deploy_before_fault")
                evidence.append(f'deploy {d["sha"]} "{d["message"]}" shipped {max(gap, 0):.0f} min before errors began')
                break

    if culprit:
        text = _deploy_text(culprit)
        if CONFIG_FILE.search(text):
            signals.append("config_diff")
            evidence.append("the deploy changed a configuration value")
        if "select " in text and ("index" in text or "migration" in text):
            signals.append("query_added")
            evidence.append("the deploy added a new query without an index")
        if "environ[" in text or "env var" in text:
            signals.append("env_rename")
            evidence.append("the deploy renamed an environment variable")
    else:
        for d in reversed(ordered):
            text = _deploy_text(d)
            if "cache" in text and ("evict" in text or "in memory" in text):
                culprit = d
                signals.append("cache_added")
                evidence.append(f'deploy {d["sha"]} "{d["message"]}" added an unbounded in-memory cache')
                break
        if culprit is None:
            if ordered:
                signals.append("deploy_not_correlated")
                latest = ordered[-1]
                evidence.append(f'latest deploy "{latest["message"]}" was not close to the start of the errors')
            else:
                signals.append("no_recent_deploy")
                evidence.append("no deploys in the last 6 hours")

    if culprit:
        data["culprit_sha"] = culprit["sha"]
        data["culprit_message"] = culprit["message"]
        patches = [f["patch"].replace("\n", " | ") for f in culprit.get("files", [])]
        data["culprit_patch"] = "; ".join(patches)[:300]
    return signals, evidence, data


async def deploy_investigation(call, svc, end, minutes):
    first = await call("logs", "first_error_time", service=svc, end=end, minutes=60)
    fault_start = parse_ts(first["ts"]) if first and first.get("ts") else None
    all_deploys = await call("github", "list_recent_deploys", service=svc, end=end, hours=240)
    end_dt = parse_ts(end)
    recent = [d for d in all_deploys if (end_dt - parse_ts(d["ts"])).total_seconds() <= 6 * 3600]
    signals, evidence, data = deploy_signals(recent, fault_start)

    sha = data.get("culprit_sha")
    if sha:
        ordered = sorted(all_deploys, key=lambda d: parse_ts(d["ts"]))
        idx = next(i for i, d in enumerate(ordered) if d["sha"] == sha)
        if idx > 0:
            data["previous_sha"] = ordered[idx - 1]["sha"]
    summary = "; ".join(evidence) if evidence else "no deploy information"
    return make_finding("deploy", signals, evidence, data, summary)


# ---------------------------------------------------------------- database
def db_signals(slow, conns):
    signals, evidence = [], []
    n_slow = sum(r["count"] for r in slow)
    if n_slow >= 3:
        signals.append("slow_queries")
        evidence.append(f'{n_slow} slow queries, e.g. "{slow[0]["message"][:80]}"')
    latest, base = conns.get("latest"), conns.get("baseline")
    if latest is not None and base:
        if latest <= 3 and base >= 4:
            signals.append("db_conn_low")
            evidence.append(f"only {latest:.0f} DB connections in use vs {base:.0f} normally (pool may be too small)")
        elif latest > 2 * base:
            signals.append("db_conn_high")
            evidence.append(f"{latest:.0f} DB connections in use vs {base:.0f} normally")
    return signals, evidence


async def db_investigation(call, svc, end, minutes):
    slow = await call("postgres", "get_slow_queries", service=svc, end=end, minutes=minutes)
    conns = await call("postgres", "get_connections", service=svc, end=end)
    signals, evidence = db_signals(slow, conns)
    summary = "; ".join(evidence) if evidence else "database looks normal"
    return make_finding("db", signals, evidence, {}, summary)
