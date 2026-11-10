"""Command line helper.

    python -m victim.chaos list
    python -m victim.chaos run bad_config            # load data into Postgres only
    python -m victim.chaos run bad_config --send     # also POST the signed alert to the API
"""
import argparse
import json
import os

from app.core.tokens import sign
from victim.generate import SCENARIOS
from victim.loader import load_scenario

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://sre:sre@localhost:5434/sre")
ALERT_URL = os.getenv("ALERT_URL", "http://localhost:8000/webhooks/alert")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "dev-secret")


def main():
    p = argparse.ArgumentParser(prog="chaos")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    run = sub.add_parser("run")
    run.add_argument("scenario", choices=list(SCENARIOS))
    run.add_argument("--send", action="store_true")
    args = p.parse_args()

    if args.cmd == "list":
        for name, spec in SCENARIOS.items():
            print(f"{name:16} {spec['description']}")
        return

    data = load_scenario(args.scenario, DATABASE_URL)
    print(f"loaded {args.scenario}: {len(data['logs'])} logs, {len(data['metrics'])} metrics, {len(data['deploys'])} deploys")
    if args.send:
        import httpx

        body = json.dumps(data["alert"]).encode()
        r = httpx.post(ALERT_URL, content=body, headers={"Content-Type": "application/json", "X-Signature": sign(WEBHOOK_SECRET, body)})
        print("alert sent:", r.status_code, r.text)
    else:
        print(json.dumps(data["alert"], indent=2))


if __name__ == "__main__":
    main()
