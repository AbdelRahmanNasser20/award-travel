#!/usr/bin/env python3
"""
Find cheap award flights via the Seats.aero Cached Search API.

Auth:  set the env var SEATS_AERO_API_KEY to your Seats.aero Pro API key.
       (This is the Seats.aero key, NOT any airline password.)

Example:
  export SEATS_AERO_API_KEY="..."
  python3 search_seats_aero.py --origin JFK,LGA,EWR --destination PHX \
      --start 2026-06-03 --end 2026-06-25 --weekdays Wed,Thu \
      --cabin economy --sources united,delta,american,jetblue \
      --max-miles 17000 --out ../report.md

Outputs a ranked table to stdout and writes a markdown report to --out.

Ranking/report logic lives in award_common (shared with the live browser tool).
"""
import argparse
import os
import sys
import urllib.parse
import urllib.request
import json

from award_common import (
    CABIN_FIELD, WEEKDAY_NUM, build_table, rank, write_report,
)

BASE = "https://seats.aero/partnerapi/search"


def parse_args():
    p = argparse.ArgumentParser(description="Find cheap award flights (Seats.aero).")
    p.add_argument("--origin", required=True, help="Comma-separated origin codes, e.g. JFK,LGA,EWR")
    p.add_argument("--destination", required=True, help="Comma-separated destination codes, e.g. PHX")
    p.add_argument("--start", required=True, help="Range start YYYY-MM-DD")
    p.add_argument("--end", required=True, help="Range end YYYY-MM-DD")
    p.add_argument("--weekdays", default="", help="Optional filter, e.g. Wed,Thu")
    p.add_argument("--cabin", default="economy", choices=list(CABIN_FIELD))
    p.add_argument("--sources", default="united,delta,american,jetblue,southwest",
                   help="Comma-separated mileage programs")
    p.add_argument("--max-miles", type=int, default=0, help="Budget cap in miles (0 = no cap)")
    p.add_argument("--only-direct", action="store_true", help="Direct flights only")
    p.add_argument("--out", default="report.md", help="Report output path")
    return p.parse_args()


def fetch(params, api_key):
    """Call the cached-search endpoint, following the cursor for full results."""
    results, cursor = [], None
    while True:
        q = dict(params)
        if cursor:
            q["cursor"] = cursor
        url = BASE + "?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={
            "Partner-Authorization": api_key,
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=40) as r:
            payload = json.load(r)
        data = payload.get("data", payload if isinstance(payload, list) else [])
        results.extend(data)
        cursor = payload.get("cursor") if isinstance(payload, dict) else None
        if not cursor or not data:
            break
    return results


def main():
    args = parse_args()
    api_key = os.environ.get("SEATS_AERO_API_KEY")
    if not api_key:
        sys.exit("ERROR: set SEATS_AERO_API_KEY env var (your Seats.aero Pro API key).")

    allowed_wd = {WEEKDAY_NUM[w.strip().title()[:3]] for w in args.weekdays.split(",") if w.strip()}
    params = {
        "origin_airport": args.origin,
        "destination_airport": args.destination,
        "start_date": args.start,
        "end_date": args.end,
        "cabin": args.cabin,
        "sources": args.sources,
        "order_by": "lowest_mileage",
        "take": 1000,
    }
    if args.only_direct:
        params["only_direct_flights"] = "true"

    print(f"Searching {args.origin} -> {args.destination}, {args.start}..{args.end}, "
          f"{args.cabin}, programs: {args.sources} ...", file=sys.stderr)
    raw = fetch(params, api_key)
    rows = rank(raw, args.cabin, allowed_wd, args.max_miles)

    if not rows:
        print("No award space found for those parameters.", file=sys.stderr)
    print(build_table(rows, args.origin, args.destination))

    write_report(args.out, args.origin, args.destination, rows,
                 start=args.start, end=args.end, cabin=args.cabin,
                 weekdays=args.weekdays, sources=args.sources, max_miles=args.max_miles)
    print(f"\nReport written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
