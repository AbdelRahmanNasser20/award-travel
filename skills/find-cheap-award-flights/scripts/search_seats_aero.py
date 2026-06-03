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
"""
import argparse
import datetime as dt
import os
import sys
import urllib.parse
import urllib.request
import json

BASE = "https://seats.aero/partnerapi/search"

CABIN_FIELD = {  # which mileage-cost field maps to each cabin
    "economy": "YMileageCost",
    "premium": "WMileageCost",
    "business": "JMileageCost",
    "first": "FMileageCost",
}
WEEKDAY_NUM = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


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


def weekday_ok(date_str, allowed):
    if not allowed:
        return True
    try:
        d = dt.date.fromisoformat(date_str[:10])
    except ValueError:
        return True
    return d.weekday() in allowed


def rank(results, cabin, allowed_wd, max_miles):
    field = CABIN_FIELD[cabin]
    rows = []
    for a in results:
        miles = a.get(field) or 0
        try:
            miles = int(miles)
        except (TypeError, ValueError):
            miles = 0
        if miles <= 0:
            continue
        date = a.get("Date") or a.get("date") or ""
        if not weekday_ok(date, allowed_wd):
            continue
        taxes = a.get("TotalTaxes")
        rows.append({
            "date": date[:10],
            "program": a.get("Source") or a.get("source") or "?",
            "miles": miles,
            "taxes": taxes,
            "direct": a.get("Direct") or a.get(field.replace("MileageCost", "Direct")),
            "id": a.get("ID") or a.get("id") or "",
        })
    rows.sort(key=lambda x: (x["miles"], x["taxes"] or 0))
    for r in rows:
        if max_miles and r["miles"] <= max_miles:
            r["deal"] = "✅"
        elif max_miles and r["miles"] <= max_miles * 1.15:
            r["deal"] = "⚠️"
        elif max_miles:
            r["deal"] = "❌"
        else:
            r["deal"] = "—"
    return rows


def fmt_taxes(t):
    if t is None:
        return "?"
    try:
        return f"${float(t)/100:,.0f}" if float(t) > 1000 else f"${float(t):,.0f}"
    except (TypeError, ValueError):
        return str(t)


def booking_link(row, origin, dest):
    if row["id"]:
        return f"https://seats.aero/search?id={row['id']}"
    return ("https://www.google.com/travel/flights?q=" +
            urllib.parse.quote(f"Flights {origin} to {dest} on {row['date']}"))


def build_table(rows, origin, dest):
    head = ("| Date | Program | Miles | + Taxes | Deal | Book |\n"
            "|------|---------|-------|---------|------|------|\n")
    body = ""
    for r in rows:
        body += (f"| {r['date']} | {r['program']} | {r['miles']:,} | "
                 f"{fmt_taxes(r['taxes'])} | {r['deal']} | "
                 f"[link]({booking_link(r, origin, dest)}) |\n")
    return head + body


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
    table = build_table(rows, args.origin, args.destination)
    print(table)

    best = rows[0] if rows else None
    report = (
        f"# Cheap Award Flights — {args.origin} → {args.destination}\n\n"
        f"_Generated {dt.datetime.now():%Y-%m-%d %H:%M} • Source: Seats.aero Cached Search_\n\n"
        f"**Search:** {args.origin} → {args.destination}, {args.start} to {args.end}, "
        f"cabin **{args.cabin}**, weekdays: {args.weekdays or 'any'}, "
        f"programs: {args.sources}, budget ≤ {args.max_miles or 'none'} miles.\n\n"
    )
    if best:
        report += (f"## Best pick\n**{best['miles']:,} miles + {fmt_taxes(best['taxes'])}** on "
                   f"**{best['program']}**, {best['date']}. "
                   f"[Book]({booking_link(best, args.origin, args.destination)})\n\n"
                   "_Award space moves fast — book promptly._\n\n")
    report += "## All results (cheapest first)\n\n" + table
    report += ("\n> Award availability is volatile and the airline site is the final source "
               "of truth. Confirm miles + fees there before booking.\n")

    with open(args.out, "w") as f:
        f.write(report)
    print(f"\nReport written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
