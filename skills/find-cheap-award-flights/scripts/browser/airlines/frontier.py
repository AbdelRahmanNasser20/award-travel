#!/usr/bin/env python3
"""Frontier (Frontier Miles) award-flight scraper — Playwright SYNC API.

SKILL.md notes used here:
  - Entry point: https://www.flyfrontier.com (Frontier Miles).
  - Enable the "Frontier Miles" toggle (award/miles fare display) BEFORE reading
    prices, otherwise the page shows cash dollars instead of miles.
  - Frontier only searches ONE airport at a time, so the runner loops each origin
    airport and de-dupes the pooled rows with airports.merge_dedupe (hence
    SUPPORTS_METRO = False — query.origin_airports holds exactly one airport).
  - Iterate query.dates() and read the cheapest miles per flight per date.
  - Frontier Miles is effectively single-cabin economy, so the miles value goes in
    YMileageCost; there are no premium-cabin award buckets.

CANNOT be tested live, so every selector below is a best-effort guess and is marked
`# VERIFY`. Any failure returns [] and warns on stderr so one airline never sinks
the whole run.
"""
import sys

from browser.session import human_type, human_pause, goto

SUPPORTS_METRO = False
HOME_URL = "https://www.flyfrontier.com"


def _warn(msg):
    print(f"[frontier] {msg}", file=sys.stderr)


def _miles_to_int(text):
    """'12,300 miles' / '12.3k' -> int miles, or None."""
    if not text:
        return None
    t = str(text).lower().replace(",", "").strip()
    digits = ""
    for ch in t:
        if ch.isdigit():
            digits += ch
        elif ch == "." and "k" in t:
            digits += "."
    if not digits:
        return None
    try:
        val = float(digits)
        if "k" in t and val < 1000:
            val *= 1000
        return int(round(val))
    except ValueError:
        return None


def _cash_to_float(text):
    """'$5.60' / 'USD 11.20' -> 5.6, or 0.0."""
    if not text:
        return 0.0
    keep = "".join(c for c in str(text) if c.isdigit() or c == ".")
    try:
        return float(keep) if keep else 0.0
    except ValueError:
        return 0.0


def _hhmm(text):
    """'7:05 AM' -> '07:05' (24h). Best-effort; returns '' on failure."""
    if not text:
        return ""
    t = str(text).strip().upper()
    ampm = None
    if "AM" in t:
        ampm, t = "AM", t.replace("AM", "")
    elif "PM" in t:
        ampm, t = "PM", t.replace("PM", "")
    t = t.strip()
    if ":" not in t:
        return ""
    try:
        h, m = t.split(":")[0:2]
        h, m = int(h), int(m[:2])
    except (ValueError, IndexError):
        return ""
    if ampm == "PM" and h != 12:
        h += 12
    if ampm == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{m:02d}"


def _within_window(depart_hhmm, query):
    if not depart_hhmm:
        return True
    try:
        h, m = depart_hhmm.split(":")
        t = __import__("datetime").time(int(h), int(m))
    except (ValueError, AttributeError):
        return True
    if query.depart_after and t < query.depart_after:
        return False
    if query.depart_before and t > query.depart_before:
        return False
    return True


def _enable_miles_toggle(page):
    """Flip the Frontier Miles / award-fare toggle so prices show in miles."""
    selectors = [
        "input[type='checkbox'][name*='miles' i]",          # VERIFY
        "button:has-text('Frontier Miles')",                # VERIFY
        "[data-test='miles-toggle']",                       # VERIFY
        "label:has-text('Use Frontier Miles')",             # VERIFY
        "input#searchWithMiles",                            # VERIFY
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                loc.click()
                human_pause()
                return True
        except Exception:
            continue
    return False


def signature(page):
    """Cheap presence check: are Frontier's result selectors on the page?"""
    selectors = [
        "[data-test='flight-card']",      # VERIFY
        ".flight-results",                # VERIFY
        "[class*='FlightCard']",          # VERIFY
        "li[class*='flight']",            # VERIFY
    ]
    for sel in selectors:
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


def _search_one_date(page, query, origin, dest, d):
    """Run a single-date one-way search and return raw rows for that date."""
    rows = []
    date_str = d.isoformat()
    # Deep link to the one-way miles search for this date. # VERIFY url shape.
    url = (
        f"{HOME_URL}/booking/select-flights"
        f"?origin={origin}&destination={dest}"
        f"&departureDate={date_str}&adults=1&fareType=miles&type=oneway"
    )
    deeplink = url
    try:
        goto(page, url)
    except Exception as e:
        _warn(f"goto failed for {origin}->{dest} {date_str}: {e}")
        # Fall back to typing into the form on the home page. # VERIFY selectors.
        try:
            goto(page, HOME_URL)
            human_type(page.locator("input[name='origin']").first, origin)          # VERIFY
            human_pause()
            human_type(page.locator("input[name='destination']").first, dest)       # VERIFY
            human_pause()
            human_type(page.locator("input[name='departureDate']").first, date_str)  # VERIFY
            human_pause()
            page.locator("button[type='submit']").first.click()                     # VERIFY
            human_pause(1.5, 3.0)
        except Exception as e2:
            _warn(f"form fallback failed {origin}->{dest} {date_str}: {e2}")
            return rows

    _enable_miles_toggle(page)
    human_pause(1.0, 2.0)

    try:
        cards = page.locator("[data-test='flight-card']")  # VERIFY
        if cards.count() == 0:
            cards = page.locator("[class*='FlightCard']")  # VERIFY
        n = cards.count()
    except Exception as e:
        _warn(f"no flight cards {origin}->{dest} {date_str}: {e}")
        return rows

    for i in range(n):
        try:
            card = cards.nth(i)

            def txt(sel):
                try:
                    el = card.locator(sel).first
                    return el.inner_text().strip() if el.count() > 0 else ""
                except Exception:
                    return ""

            depart = _hhmm(txt("[data-test='depart-time']"))   # VERIFY
            arrive = _hhmm(txt("[data-test='arrive-time']"))   # VERIFY
            miles = _miles_to_int(txt("[data-test='miles-price']"))  # VERIFY
            taxes = _cash_to_float(txt("[data-test='taxes']"))       # VERIFY
            flight_no = txt("[data-test='flight-number']") or "F9"   # VERIFY
            stops_txt = txt("[data-test='stops']").lower()           # VERIFY
            direct = ("nonstop" in stops_txt) or ("0 stop" in stops_txt) or (stops_txt == "")

            if miles is None or miles <= 0:
                continue
            if not _within_window(depart, query):
                continue

            rows.append({
                "Source": "frontier",
                "YMileageCost": int(miles),
                "TotalTaxes": taxes,
                "Date": date_str,
                "Direct": bool(direct),
                "OriginAirport": origin,
                "DestinationAirport": dest,
                "FlightNumbers": flight_no.replace(" ", ""),
                "DepartTime": depart,
                "ArriveTime": arrive,
                "DeepLink": deeplink,
            })
        except Exception as e:
            _warn(f"row parse error {origin}->{dest} {date_str} #{i}: {e}")
            continue
    return rows


def scrape(page, query):
    """Loop query.dates() for the single origin/dest pair and return raw rows."""
    try:
        origin = query.origin_airports[0]  # exactly one — runner loops airports
    except (IndexError, AttributeError) as e:
        _warn(f"no origin airport: {e}")
        return []

    all_rows = []
    try:
        for dest in query.dest_airports:
            for d in query.dates():
                all_rows.extend(_search_one_date(page, query, origin, dest, d))
                human_pause()
    except Exception as e:
        _warn(f"scrape failed: {e}")
        return []
    return all_rows
