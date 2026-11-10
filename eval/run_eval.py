"""Runs every scenario through the live system and scores it against the answer key.

    python -m eval.run_eval              # all scenarios, 1 run each
    python -m eval.run_eval --runs 3     # 3 runs each
    python -m eval.run_eval --only bad_config traffic_spike

The system must be running (docker compose up). Approvals are clicked for you.
"""
import argparse
import json
import statistics
import time

import httpx

from victim.generate import SCENARIOS

BASE = "http://localhost:8000"
FINAL = {"resolved", "closed_no_action", "escalated"}


def run_one(client, name, timeout=180):
    started = time.time()
    incident_id = client.post(f"{BASE}/dev/scenarios/{name}").json()["incident_id"]
    approved = False
    while time.time() - started < timeout:
        inc = client.get(f"{BASE}/incidents/{incident_id}").json()
        if inc["status"] == "awaiting_approval" and not approved:
            time_to_hypothesis = time.time() - started
            client.post(f"{BASE}/incidents/{incident_id}/decision", json={"decision": "approve", "decided_by": "eval"})
            approved = True
        if inc["status"] in FINAL:
            got = (inc.get("hypothesis") or {}).get("category")
            return {
                "scenario": name,
                "expected": SCENARIOS[name]["expected"]["category"],
                "got": got,
                "correct": got == SCENARIOS[name]["expected"]["category"],
                "status": inc["status"],
                "seconds": round(time.time() - started, 1),
            }
        time.sleep(1.5)
    return {"scenario": name, "expected": SCENARIOS[name]["expected"]["category"], "got": None, "correct": False, "status": "timeout", "seconds": timeout}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--only", nargs="*")
    args = p.parse_args()

    names = args.only or list(SCENARIOS)
    results = []
    with httpx.Client(timeout=30) as client:
        for name in names:
            for i in range(args.runs):
                r = run_one(client, name)
                results.append(r)
                mark = "ok  " if r["correct"] else "MISS"
                print(f"{mark} {name:16} expected={r['expected']:16} got={r['got']!s:16} {r['status']:16} {r['seconds']}s")

    correct = sum(r["correct"] for r in results)
    print(f"\naccuracy: {correct}/{len(results)} = {correct / len(results):.0%}")
    print(f"median time: {statistics.median(r['seconds'] for r in results):.1f}s")
    with open("eval/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("saved eval/results.json")


if __name__ == "__main__":
    main()
