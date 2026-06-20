#!/usr/bin/env python3
"""
Shared helpers for the award-flight tools.

`search_seats_aero.py` (cached Seats.aero API) and the live browser scrapers both
produce the SAME raw result-dict shape and funnel it through `rank` -> `build_table`
-> `write_report` here, so the cached and live paths share one ranking/report engine.

Raw result-dict shape (keys read by `rank`):
    Source                  program name, e.g. "united"
    YMileageCost            economy miles    (W/J/F = premium/business/first)
    TotalTaxes              cash fees/taxes (cents or dollars; fmt_taxes normalizes)
    Date                    "YYYY-MM-DD"
    Direct                  truthy if nonstop
    ID                      id for a Seats.aero booking link (cached path only)
Live scrapers additionally set these, which `rank` PASSES THROUGH when present
(Seats.aero rows lack them, so its output is unchanged):
    OriginAirport, DestinationAirport, FlightNumbers, DepartTime, ArriveTime, DeepLink
"""
import datetime as dt
import urllib.parse

CABIN_FIELD = {  # which mileage-cost field maps to each cabin
    "economy": "YMileageCost",
    "premium": "WMileageCost",
    "business": "JMileageCost",
    "first": "FMileageCost",
}
WEEKDAY_NUM = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

# Per-flight extras that the live scrapers attach and `rank` should preserve.
PASSTHROUGH_KEYS = (
    "OriginAirport", "DestinationAirport", "FlightNumbers",
    "DepartTime", "ArriveTime", "DeepLink",
)


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
        row = {
            "date": date[:10],
            "program": a.get("Source") or a.get("source") or "?",
            "miles": miles,
            "taxes": taxes,
            "direct": a.get("Direct") or a.get(field.replace("MileageCost", "Direct")),
            "id": a.get("ID") or a.get("id") or "",
        }
        # Pass through live-scraper extras (favoriting, time filtering, reload).
        for k in PASSTHROUGH_KEYS:
            v = a.get(k)
            if v is not None:
                row[k] = v
        rows.append(row)
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
    if row.get("DeepLink"):
        return row["DeepLink"]
    if row.get("id"):
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


def write_report(out_path, origin, dest, rows, *, start, end, cabin, weekdays,
                 sources, max_miles, source_label="Seats.aero Cached Search"):
    """Write the markdown report. Default source_label keeps the cached path's
    output byte-identical (modulo the generation timestamp)."""
    table = build_table(rows, origin, dest)
    best = rows[0] if rows else None
    report = (
        f"# Cheap Award Flights — {origin} → {dest}\n\n"
        f"_Generated {dt.datetime.now():%Y-%m-%d %H:%M} • Source: {source_label}_\n\n"
        f"**Search:** {origin} → {dest}, {start} to {end}, "
        f"cabin **{cabin}**, weekdays: {weekdays or 'any'}, "
        f"programs: {sources}, budget ≤ {max_miles or 'none'} miles.\n\n"
    )
    if best:
        report += (f"## Best pick\n**{best['miles']:,} miles + {fmt_taxes(best['taxes'])}** on "
                   f"**{best['program']}**, {best['date']}. "
                   f"[Book]({booking_link(best, origin, dest)})\n\n"
                   "_Award space moves fast — book promptly._\n\n")
    report += "## All results (cheapest first)\n\n" + table
    report += ("\n> Award availability is volatile and the airline site is the final source "
               "of truth. Confirm miles + fees there before booking.\n")
    with open(out_path, "w") as f:
        f.write(report)
    return report
