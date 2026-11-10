"""Replays every scenario through the real investigator code with a fake tool layer.

No database, no network, no LLM. The fake mirrors what the MCP servers do in SQL.
"""
import asyncio
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from app.orchestrator import analysis, heuristics
from victim.generate import SCENARIOS, generate

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
END = NOW.isoformat()
BAD = ("ERROR", "WARN")


class FakeTools:
    def __init__(self, name):
        self.d = generate(name, now=NOW)

    async def __call__(self, server, tool, **args):
        return getattr(self, f"{server}_{tool}")(**args)

    def _logs(self, minutes, service=None):
        lo, hi = NOW - timedelta(minutes=minutes), NOW + timedelta(minutes=1)
        return [l for l in self.d["logs"] if l["level"] in BAD and lo <= l["ts"] <= hi and (service is None or l["service"] == service)]

    def logs_top_error_messages(self, service, end, minutes):
        c = Counter(re.sub(r"[0-9]+", "N", l["message"]) for l in self._logs(minutes, service))
        return [{"message": m, "count": n} for m, n in c.most_common(8)]

    def logs_count_errors(self, service, end, minutes):
        rows = self._logs(minutes, service)
        last = max((r["ts"] for r in rows), default=None)
        return {
            "errors": sum(r["level"] == "ERROR" for r in rows),
            "warns": sum(r["level"] == "WARN" for r in rows),
            "error_minutes": len({r["ts"].replace(second=0) for r in rows}),
            "last_error_age_min": None if last is None else max(0.0, (NOW - last).total_seconds() / 60),
        }

    def logs_services_with_errors(self, end, minutes):
        c = Counter(r["service"] for r in self._logs(minutes))
        return [{"service": s, "errors": n} for s, n in c.most_common()]

    def logs_first_error_time(self, service, end, minutes):
        rows = self._logs(minutes, service)
        return {"ts": min((r["ts"] for r in rows), default=None)}

    def metrics_compare_windows(self, service, name, end, recent_minutes, baseline_start, baseline_end):
        rows = sorted(
            (m for m in self.d["metrics"] if m["service"] == service and m["name"] == name and NOW - timedelta(minutes=baseline_start) <= m["ts"] <= NOW),
            key=lambda m: m["ts"],
        )
        base = [r["value"] for r in rows if r["ts"] <= NOW - timedelta(minutes=baseline_end)]
        recent = [r["value"] for r in rows if r["ts"] >= NOW - timedelta(minutes=recent_minutes)]
        return {
            "baseline_avg": sum(base) / len(base),
            "recent_avg": sum(recent) / len(recent),
            "latest": rows[-1]["value"],
            "max_recent": max(recent),
        }

    def github_list_recent_deploys(self, service, end, hours):
        lo, hi = NOW - timedelta(hours=hours), NOW + timedelta(minutes=1)
        return [d for d in self.d["deploys"] if d["service"] == service and lo <= d["ts"] <= hi]

    def postgres_get_slow_queries(self, service, end, minutes):
        c = Counter(re.sub(r"[0-9]+", "N", l["message"]) for l in self._logs(minutes, service) if "slow query" in l["message"].lower())
        return [{"message": m, "count": n} for m, n in c.most_common(5)]

    def postgres_get_connections(self, service, end):
        rows = sorted(
            (m for m in self.d["metrics"] if m["service"] == service and m["name"] == "db_connections_in_use"),
            key=lambda m: m["ts"],
        )
        early = [r["value"] for r in rows[:15]]
        return {"latest": rows[-1]["value"], "baseline": sum(early) / len(early)}


def investigate(name):
    tools = FakeTools(name)
    alert = tools.d["alert"]
    svc = alert["service"]

    async def run():
        return [
            await analysis.logs_investigation(tools, svc, END, 15),
            await analysis.metrics_investigation(tools, svc, END, 15),
            await analysis.deploy_investigation(tools, svc, END, 15),
            await analysis.db_investigation(tools, svc, END, 15),
        ]

    findings = asyncio.run(run())
    hypothesis = heuristics.classify(findings, alert)
    return tools.d, findings, hypothesis


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_scenario_is_diagnosed_correctly(name):
    d, findings, hypothesis = investigate(name)
    expected = d["expected"]
    assert hypothesis["category"] == expected["category"], hypothesis["scores"]
    assert hypothesis["service"] == expected["service"]
    assert hypothesis["confidence"] >= 0.6


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_critic_accepts_the_correct_theory(name):
    d, findings, hypothesis = investigate(name)
    verdict = heuristics.review(hypothesis, findings, d["alert"])
    assert verdict["accepted"], verdict["reasons"]


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_proposed_action_matches_answer_key(name):
    d, findings, hypothesis = investigate(name)
    action = heuristics.propose(hypothesis, findings)
    assert action["type"] == d["expected"]["action"]
    if action["type"] == "rollback_service":
        assert action["version"]  # we found a version to go back to


def test_bad_config_rollback_goes_to_the_version_before_the_culprit():
    d, findings, hypothesis = investigate("bad_config")
    action = heuristics.propose(hypothesis, findings)
    culprit = next(x for x in d["deploys"] if x["message"] == "tune db pool for cost savings")
    older = [x for x in d["deploys"] if x["service"] == "payments" and x["ts"] < culprit["ts"]]
    assert action["version"] == max(older, key=lambda x: x["ts"])["sha"]


def test_traffic_spike_is_not_blamed_on_the_decoy_deploy():
    _, findings, hypothesis = investigate("traffic_spike")
    assert hypothesis["category"] == "traffic_spike"
    assert "deploy_before_fault" not in heuristics.merge_findings(findings)[0]


def test_critic_rejects_a_deploy_theory_when_there_is_no_deploy():
    d, findings, _ = investigate("traffic_spike")
    wrong = {"category": "config_change", "service": "payments", "cause": "x", "evidence": [], "confidence": 0.8}
    verdict = heuristics.review(wrong, findings, d["alert"])
    assert not verdict["accepted"]
