"""The rule engine. Used when no LLM key is set, and as a safety net / hint when one is.

All plain Python so it can be unit tested.
"""

# category -> {signal: weight}. A category's score is the share of its weight that was observed.
CATEGORY_SIGNALS = {
    "config_change": {"pool_errors": 3, "deploy_before_fault": 2, "config_diff": 3, "error_spike": 1, "db_conn_low": 1},
    "slow_query": {"slow_queries": 3, "latency_spike": 2, "query_added": 3, "deploy_before_fault": 1, "db_conn_high": 1},
    "memory_leak": {"memory_ramp": 4, "cache_added": 3, "memory_logs": 2},
    "crash_loop": {"crash_logs": 3, "requests_zero": 3, "env_rename": 3, "deploy_before_fault": 1},
    "dependency_down": {"upstream_unreachable": 4, "dependency_failing": 4},
    "traffic_spike": {"request_spike": 4, "cpu_high": 2, "overload_logs": 2, "deploy_not_correlated": 1},
    "false_alarm": {"transient_only": 4, "recovered": 4},
}
CATEGORIES = list(CATEGORY_SIGNALS) + ["unknown"]

ACTIONS = {
    "config_change": "rollback_service",
    "slow_query": "rollback_service",
    "crash_loop": "rollback_service",
    "memory_leak": "restart_container",
    "dependency_down": "restart_container",
}

FOLLOW_UPS = {
    "config_change": ["Add a config validation step to the deploy pipeline", "Alert on connection pool saturation"],
    "slow_query": ["Add the missing index and redeploy", "Review new queries in code review with EXPLAIN"],
    "memory_leak": ["Add an eviction policy or size limit to the cache", "Alert on memory growth rate"],
    "crash_loop": ["Fail the deploy when a required env var is missing", "Add a startup check in CI"],
    "dependency_down": ["Add a circuit breaker and clearer upstream errors", "Add a health check alert for the dependency"],
    "traffic_spike": ["Review autoscaling and rate limits", "Load test before the next campaign"],
    "false_alarm": ["Tune the alert threshold or add a longer evaluation window"],
    "unknown": ["Investigate manually and add this case to the runbooks"],
}


def merge_findings(findings):
    signals, evidence, data = set(), [], {}
    for f in findings:
        signals.update(f.get("signals", []))
        for e in f.get("evidence", []):
            if e not in evidence:
                evidence.append(e)
        data.update(f.get("data", {}))
    return signals, evidence, data


def _cause(category, data, service):
    sha, msg = data.get("culprit_sha"), data.get("culprit_message")
    patch = data.get("culprit_patch", "")
    text = {
        "config_change": f'Release {sha} ("{msg}") changed a configuration value ({patch}), which exhausted the database connection pool of {service}.',
        "slow_query": f'Release {sha} ("{msg}") added a query without an index, so {service} slowed down ({patch}).',
        "memory_leak": f'Release {sha} ("{msg}") added a cache that is never emptied, so {service} keeps growing in memory.',
        "crash_loop": f'Release {sha} ("{msg}") renamed an environment variable that is not set, so {service} crashes on startup.',
        "dependency_down": f"{service} is down, and the service that raised the alert depends on it.",
        "traffic_spike": f"A sudden jump in traffic is overloading {service}. No release is responsible.",
        "false_alarm": f"A brief blip in {service} that already recovered. No action is needed.",
        "unknown": f"The evidence does not clearly point to one cause for {service}.",
    }
    return text[category]


def classify(findings, alert):
    signals, evidence, data = merge_findings(findings)
    scores = {}
    for category, weights in CATEGORY_SIGNALS.items():
        scores[category] = sum(w for s, w in weights.items() if s in signals) / sum(weights.values())

    best = max(scores, key=scores.get)
    category = best if scores[best] >= 0.5 else "unknown"
    service = alert["service"]
    if category == "dependency_down" and data.get("dependency"):
        service = data["dependency"]
    return {
        "category": category,
        "service": service,
        "cause": _cause(category, data, service),
        "evidence": evidence[:8],
        "confidence": round(min(scores[best], 1.0) * 0.95, 2),
        "scores": {k: round(v, 2) for k, v in scores.items()},
    }


def review(hypothesis, findings, alert):
    """The critic: try to find reasons the theory could be wrong."""
    signals, _, _ = merge_findings(findings)
    category, reasons = hypothesis["category"], []
    if category == "unknown":
        reasons.append("No category has enough supporting evidence")
    if category in ("config_change", "crash_loop", "slow_query") and "deploy_before_fault" not in signals:
        reasons.append("No deploy shortly before the errors began, so a release cannot be blamed")
    if category != "traffic_spike" and "request_spike" in signals:
        reasons.append("Traffic spiked, which could explain the symptoms on its own")
    if category != "dependency_down" and "dependency_failing" in signals:
        reasons.append("Another service is failing, this service may only be a victim")
    if hypothesis["confidence"] < 0.6:
        reasons.append(f"Confidence {hypothesis['confidence']:.2f} is below 0.6")
    return {
        "accepted": not reasons,
        "reasons": reasons or ["Timing, alternative causes and evidence checked, the theory holds up"],
    }


def propose(hypothesis, findings):
    category, service = hypothesis["category"], hypothesis["service"]
    _, _, data = merge_findings(findings)
    action_type = ACTIONS.get(category)
    if not action_type:
        return {
            "type": "none",
            "target": service,
            "risk": "none",
            "rationale": "Nothing needs to change in production for this kind of incident.",
        }
    action = {"type": action_type, "target": service, "risk": "low"}
    if action_type == "rollback_service":
        previous = data.get("previous_sha")
        if not previous:
            return {"type": "none", "target": service, "risk": "none", "rationale": "No earlier version found to roll back to."}
        action["version"] = previous
        action["rationale"] = f"Roll {service} back to {previous}, the version before the suspect release {data.get('culprit_sha')}."
    else:
        action["rationale"] = f"Restart {service} to clear the bad state."
    return action


def guess_severity(alert) -> str:
    text = f"{alert['alert_name']} {alert['summary']}".lower()
    if alert["service"] == "payments" or "down" in text or "no successful" in text:
        return "critical"
    if "latency" in text or "memory" in text:
        return "high"
    return "medium"


def postmortem_markdown(incident, hypothesis, findings, action, execution, verified, final_status, timeline):
    lines = [
        f"# Postmortem: {incident['title']}",
        "",
        "## Summary",
        f"- Service: {incident['service']}",
        f"- Severity: {incident['severity']}",
        f"- Outcome: {final_status.replace('_', ' ')}",
        "",
        "## Root cause",
        hypothesis["cause"],
        f"Confidence: {hypothesis['confidence']:.0%} (category: {hypothesis['category']})",
        "",
        "## Evidence",
        *[f"- {e}" for e in hypothesis["evidence"]],
        "",
        "## What was done",
    ]
    if action and action.get("type") != "none":
        lines.append(f"- Proposed: {action['type']} on {action['target']}. {action.get('rationale', '')}")
        lines.append(f"- Execution: {'completed' if execution else 'not executed'}")
        lines.append(f"- Verified recovered: {'yes' if verified else 'no'}")
    else:
        lines.append("- No production change was needed.")
    lines += ["", "## Timeline", *[f"- {t['at'][11:19]} {t['agent']}: {t['message']}" for t in timeline[:30]]]
    lines += ["", "## Follow-ups", *[f"- {f}" for f in FOLLOW_UPS.get(hypothesis["category"], FOLLOW_UPS["unknown"])]]
    return "\n".join(lines)
