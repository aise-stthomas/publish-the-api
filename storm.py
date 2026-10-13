"""Storm: many requests at once, to see the gateway's throttle answer before the function runs.

    uv run storm.py              # 20 requests at once to GET / on your API (no model call, no token needed)
    uv run storm.py --n 50       # more
    uv run storm.py --triage     # the same against POST /triage: every 200 is a model call, so keep n small

Prints how many answered 200, how many 429 (throttled at the gateway), and anything else,
with the time each took. A 429 costs nothing: the function never ran.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

load_dotenv()


def one(url: str, body: bytes | None, token: str | None) -> tuple[int, float]:
    headers = {"content-type": "application/json"}
    if token:
        headers["x-lab-token"] = token
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            code = resp.status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception:
        code = 0
    return code, time.perf_counter() - t0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n", type=int, default=20, help="requests, all at once")
    p.add_argument("--triage", action="store_true", help="POST /triage (a model call per 200) instead of GET /")
    p.add_argument("--url", default=os.environ.get("LAB_URL"), help="the API's /triage URL (default: LAB_URL from .env)")
    args = p.parse_args()
    if not args.url:
        raise SystemExit("no URL: run ./deploy.sh, or pass --url")
    base = args.url.rsplit("/triage", 1)[0]
    if args.triage:
        url = args.url
        body = open(os.path.join("src", "function", "sample-event-body.json"), "rb").read()
    else:
        url, body = base + "/", None
    print(f"{args.n} requests at once to {url}")
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.n) as ex:
        results = list(ex.map(lambda _: one(url, body, os.environ.get("LAB_TOKEN")), range(args.n)))
    wall = time.perf_counter() - t0
    counts: dict[int, int] = {}
    for code, _ in results:
        counts[code] = counts.get(code, 0) + 1
    names = {200: "200 ok", 429: "429 throttled at the gateway", 401: "401 bad token", 503: "503 the function gave up", 0: "no answer"}
    for code in sorted(counts, key=lambda c: -counts[c]):
        secs = sorted(t for c, t in results if c == code)
        print(f"  {counts[code]:>3} × {names.get(code, str(code)):<32} fastest {secs[0]*1000:>6.0f} ms · slowest {secs[-1]*1000:>6.0f} ms")
    print(f"  all {args.n} answered in {wall:.1f} s")
    print(json.dumps({"n": args.n, "counts": counts, "wall_s": round(wall, 2)}))


if __name__ == "__main__":
    main()
