#!/usr/bin/env python3
"""Southwest (Rapid Rewards points) award-flight scraper — Playwright SYNC API.

Notes from SKILL.md:
- Southwest — https://www.southwest.com (select "Points"). It shows POINTS without
  login, so we flip the fare-type toggle to "Points" before searching — no auth needed.
- Date deep links work, so we iterate query.dates() and read the points-per-flight
  for each date (one airport at a time — Southwest does not accept metro areas, so the
  runner loops each airport and de-dupes; query.origin_airports holds exactly ONE here).
- Southwest only sells ECONOMY, so the points value lands in YMileageCost regardless
  of query.cabin.

Cannot test live: selectors below are best-effort and EVERY guess is marked `# VERIFY`.
"""
import sys
from datetime import date

from browser.session import human_type, human_pause, goto

SUPPORTS_METRO = False
HOME_URL = "https://www.southwest.com"

# VERIFY: container/row selectors for the fare results grid on the booking page.
_RESULTS_SELECTOR = "div.air-booking-select-detail, ul.air-booking-select-detail"  # VERIFY
_ROW_SELECTOR = "li.air-booking-select-detail--flight, div[role='row'].flight-row"  # VERIFY


def _fmt_date(d: date) -> str:
    """Southwest deep links expect M/D/YYYY (no zero-pad)."""
    return f"{d.month}/{d.day}/{d.year}"  # VERIFY (date format in the URL query string)


def _deep_link(origin: str, dest: str, d: date) -> str:
    """Build a points-mode shopping URL that reopens this exact date's results."""
    # VERIFY: the air/shopping path + query params (fareType, passengers, dates).
    return (
        f"{HOME_URL}/air/booking/select.html"
        f"?adultPassengersCount=1&departureDate={_fmt_date(d)}"
        f"&destinationAirportCode={dest}&fareType=POINTS"
        f"&originationAirportCode={origin}&tripType=oneway&reset=true"
    )


def _hhmm(raw: str) -> str:
    """Normalize a Southwest time label like '7:00 AM' to 24h 'HH:MM'. Best effort."""
    if not raw:
        return ""
    raw = raw.strip().upper().replace(".", "")
    try:
        ampm = ""
        if "AM" in raw or "PM" in raw:
            ampm = "AM" if "AM" in raw else "PM"
            raw = raw.replace("AM", "").replace("PM", "").strip()
        hh, mm = raw.split(":")
        h, m = int(hh), int(mm)
        if ampm == "PM" and h != 12:
            h += 12
        if ampm == "AM" and h == 12:
            h = 0
        return f"{h:02d}:{m:02d}"
    except Exception:
        return raw


def _to_int(raw: str) -> int:
    """Pull the integer out of a label like '7,389 pts' or '12,500'."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    return int(digits) if digits else 0


def _passes_time(depart_hhmm: str, query) -> bool:
    """Respect depart_after/depart_before; leave points filtering to the ranker."""
    if not depart_hhmm or ":" not in depart_hhmm:
        return True
    try:
        h, m = depart_hhmm.split(":")
        from datetime import time as _t
        t = _t(int(h), int(m))
    except Exception:
        return True
    if query.depart_after and t < query.depart_after:
        return False
    if query.depart_before and t > query.depart_before:
        return False
    return True


def _select_points_toggle(page) -> None:
    """Flip the fare-type toggle to 'Points' before searching (no login needed)."""
    # VERIFY: the radio/toggle that switches dollars -> points on the home search form.
    for sel in (
        "input#bookingType-points",                 # VERIFY
        "label[for='bookingType-points']",          # VERIFY
        "button[aria-label*='Points']",             # VERIFY
        "text=Points",                              # VERIFY (last-ditch text match)
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.click(timeout=4000)
                human_pause()
                return
        except Exception:
            continue


def _scrape_date(page, query, origin: str, dest: str, d: date) -> list:
    """Open one date's points results via deep link and parse each flight row."""
    rows = []
    goto(page, _deep_link(origin, dest, d))
    human_pause(1.0, 2.0)

    # Re-assert points mode in case the deep link landed on a dollar view.
    _select_points_toggle(page)

    try:
        page.wait_for_selector(_ROW_SELECTOR, timeout=15000)
    except Exception:
        return rows

    flight_rows = page.locator(_ROW_SELECTOR)
    count = flight_rows.count()
    for i in range(count):
        try:
            row = flight_rows.nth(i)

            # VERIFY: flight number cell (e.g. "1234" or "WN 1234").
            fn_raw = row.locator(".flight-numbers--flight-number, [class*='flight-number']").first  # VERIFY
            fn = fn_raw.inner_text(timeout=2000).strip() if fn_raw.count() else ""
            fn = "".join(ch for ch in fn if ch.isdigit())
            flight_numbers = f"WN{fn}" if fn else "WN"

            # VERIFY: departure / arrival time labels.
            dep_raw = row.locator("[class*='depart'] .time--label, [class*='time-component'] .time--label").first  # VERIFY
            arr_raw = row.locator("[class*='arriv'] .time--label").first  # VERIFY
            depart = _hhmm(dep_raw.inner_text(timeout=2000)) if dep_raw.count() else ""
            arrive = _hhmm(arr_raw.inner_text(timeout=2000)) if arr_raw.count() else ""

            if not _passes_time(depart, query):
                continue

            # VERIFY: stops badge — "Nonstop" vs "1 stop".
            stops_raw = ""
            stops_loc = row.locator("[class*='stops'], .flight-stops").first  # VERIFY
            if stops_loc.count():
                stops_raw = stops_loc.inner_text(timeout=2000).strip().lower()
            direct = "nonstop" in stops_raw or "0 stop" in stops_raw

            # VERIFY: cheapest points fare button label, e.g. "7,389 pts".
            pts = 0
            pts_loc = row.locator(".fare-button--value, [class*='currency'] .swa-g-screen-reader-only, [class*='fare'] [class*='points']")  # VERIFY
            for j in range(pts_loc.count()):
                v = _to_int(pts_loc.nth(j).inner_text(timeout=2000))
                if v > 0 and (pts == 0 or v < pts):
                    pts = v
            if pts <= 0:
                continue

            # VERIFY: taxes/fees label (Southwest award fees are typically ~$5.60).
            taxes = 0.0
            tax_loc = row.locator("[class*='tax'], [class*='fees']").first  # VERIFY
            if tax_loc.count():
                t = tax_loc.inner_text(timeout=2000)
                t = "".join(ch for ch in t if ch.isdigit() or ch == ".")
                try:
                    taxes = float(t) if t else 0.0
                except ValueError:
                    taxes = 0.0

            rows.append({
                "Source": "southwest",
                "YMileageCost": pts,
                "TotalTaxes": taxes,
                "Date": d.isoformat(),
                "Direct": direct,
                "OriginAirport": origin,
                "DestinationAirport": dest,
                "FlightNumbers": flight_numbers,
                "DepartTime": depart,
                "ArriveTime": arrive,
                "DeepLink": _deep_link(origin, dest, d),
            })
        except Exception:
            continue
    return rows


def scrape(page, query) -> list:
    """Search Southwest award points for the single origin in query, across dates."""
    try:
        origin = query.origin_airports[0]
    except (IndexError, AttributeError):
        print("southwest: no origin airport in query", file=sys.stderr)
        return []

    out = []
    try:
        for dest in query.dest_airports:
            for d in query.dates():
                try:
                    out.extend(_scrape_date(page, query, origin, dest, d))
                except Exception as e:
                    print(f"southwest: date {d} {origin}->{dest} failed: {e}", file=sys.stderr)
                    continue
        return out
    except Exception as e:
        print(f"southwest: scrape failed: {e}", file=sys.stderr)
        return []


def signature(page) -> bool:
    """Cheap presence check: are Southwest's results selectors on the page?"""
    try:
        for sel in (_ROW_SELECTOR, _RESULTS_SELECTOR):
            if page.locator(sel).count() > 0:
                return True
        return False
    except Exception:
        return False
