"""Inferences: read the inference table, one item per call the function handled.

    uv run inferences.py                    # today's rows (UTC), then a summary
    uv run inferences.py --day 2026-10-13   # another day
    uv run inferences.py --days 3           # the last three days
    uv run inferences.py --json             # the rows as JSON lines, for your own scripts
    uv run inferences.py --save             # also append them to data/inference/<day>.jsonl

The table's partition key is the day and its sort key is the time, so one day is one query
and comes back in order. The same query from the CLI:

    aws dynamodb query --table-name triage-inferences --region us-east-1 \\
      --key-condition-expression "#d = :d" --expression-attribute-names '{"#d":"day"}' \\
      --expression-attribute-values '{":d":{"S":"2026-10-13"}}'
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from collections import defaultdict
from decimal import Decimal

import boto3
from dotenv import load_dotenv

load_dotenv()
TABLE = os.environ.get("INFERENCES_TABLE", "triage-inferences")


def plain(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def day_rows(table, day: str) -> list[dict]:
    from boto3.dynamodb.conditions import Key
    rows, kwargs = [], {"KeyConditionExpression": Key("day").eq(day)}
    while True:
        page = table.query(**kwargs)
        rows += [{k: plain(v) for k, v in it.items()} for it in page.get("Items", [])]
        if "LastEvaluatedKey" not in page:
            return rows
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def pct(xs, q):
    if not xs: return None
    xs = sorted(xs); return xs[min(len(xs) - 1, max(0, round(q * (len(xs) - 1))))]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--day"); p.add_argument("--days", type=int, default=1)
    p.add_argument("--json", action="store_true"); p.add_argument("--save", action="store_true")
    a = p.parse_args()
    today = dt.datetime.now(dt.timezone.utc).date()
    days = [a.day] if a.day else [(today - dt.timedelta(days=i)).isoformat() for i in range(a.days)][::-1]
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    rows = []
    for d in days:
        rs = day_rows(table, d); rows += rs
        if a.save and rs:
            os.makedirs("data/inference", exist_ok=True)
            with open(f"data/inference/{d}.jsonl", "w") as f:
                for r in rs: f.write(json.dumps(r) + "\n")
    if a.json:
        for r in rows: print(json.dumps(r))
        return
    print(f"{len(rows)} inferences in {TABLE} for {', '.join(days)}\n")
    print(f"  {'time (UTC)':<14}{'route':<8}{'build':<18}{'cold':<6}{'ms':>6}  {'action':<10}{'amount':>8}  {'model / error'}")
    for r in rows:
        t = r["ts"].split("#")[0][:12]
        print(f"  {t:<14}{r.get('route',''):<8}{str(r.get('build',''))[:17]:<18}{'cold' if r.get('cold_start') else '':<6}{str(r.get('latency_ms', r.get('elapsed_ms',''))):>6}  "
              f"{str(r.get('action','')):<10}{str(r.get('refund_amount','') or ''):>8}  {r.get('error') or r.get('model','')}")
    by = defaultdict(list)
    for r in rows: by[(r.get("build"), r.get("route"))].append(r)
    print(f"\n  {'build':<18}{'route':<8}{'calls':>6}{'errors':>7}{'cold':>6}{'p50 ms':>8}{'p95 ms':>8}   actions")
    for (build, route), rs in sorted(by.items(), key=lambda kv: str(kv[0])):
        lat = [r["latency_ms"] for r in rs if r.get("latency_ms") is not None]
        acts = defaultdict(int)
        for r in rs:
            if r.get("action"): acts[r["action"]] += 1
        print(f"  {str(build)[:17]:<18}{str(route):<8}{len(rs):>6}{sum(1 for r in rs if r.get('error')):>7}{sum(1 for r in rs if r.get('cold_start')):>6}"
              f"{str(pct(lat, .5)):>8}{str(pct(lat, .95)):>8}   {dict(acts) if acts else ''}")


if __name__ == "__main__":
    main()
