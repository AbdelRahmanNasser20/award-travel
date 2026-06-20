#!/usr/bin/env python3
"""JetBlue (TrueBlue points) award-flight scraper — Playwright SYNC API.

Per SKILL.md notes:
  - "JetBlue & Southwest show points WITHOUT login via the date deep links — fastest."
  - Entry point https://www.jetblue.com with the **TrueBlue points toggle** so the
    fare display is in POINTS, not cash.

Strategy: JetBlue exposes results via a date-keyed deep link, so we skip the homepage
form and navigate one deep link per date in query.dates(), reading the points (and
taxes) per flight. We force the points/award mode via the deep-link query string
(`isTrueBlue=true`) and, defensively, by clicking the points toggle if present.

Cabins: JetBlue sells "Blue" (economy) and "Mint" (lie-flat premium). We map
economy -> Blue -> YMileageCost and business/first -> Mint -> JMileageCost. JetBlue
has no separate premium-economy / first award cabin, so 'premium' falls back to Blue.

Cannot test live — every selector / URL parameter is a best-effort guess marked
`# VERIFY`. Any failure returns [] with a stderr warning.
"""
import sys
from datetime import datetime

from browser.session import human_pause, goto

SUPPORTS_METRO = True  # VERIFY: jetblue.com accepts a metro (e.g. "NYC") that expands to
                       # nearby airports; if the live site rejects metros and demands a
                       # single airport, we already fall back to origin_airports[0] below.

HOME_URL = "https://www.jetblue.com"

# Cabin -> (raw mileage field, JetBlue fare-class label). Economy/premium = Blue, business/first = Mint.
_CABIN_MAP = {
    "economy": ("YMileageCost", "blue"),
    "premium": ("YMileageCost", "blue"),   # VERIFY: JetBlue has no premium-economy award; use Blue.
    "business": ("JMileageCost", "mint"),
    "first": ("JMileageCost", "mint"),
}

# VERIFY: deep-link template. JetBlue's real search URL shape is roughly
#   /booking/flights?from=JFK&to=PHX&depart=2026-06-20&isMultiCity=false&noOfRoute=1
#   &lang=en&adults=1&children=0&infants=0&sharedMarket=false&roundTripFaresFlag=false
#   &usePoints=true
# The exact path + param names must be confirmed against a live booking flow.
_DEEPLINK = (
    HOME_URL + "/booking/flights"
    "?from={origin}&to={dest}&depart={date}"
    "&isMultiCity=false&noOfRoute=1&lang=en"
    "&adults=1&children=0&infants=0"
    "&sharedMarket=false&roundTripFaresFlag=false"
    "&usePoints=true"  # VERIFY: param that forces TrueBlue points (vs cash) fares
)

# VERIFY: container for one bookable flight row on the results page.
_SEL_FLIGHT_ROW = "[data-qa='flight-row'], .flight-row, [class*='AirItem'], li[class*='flight']"
# VERIFY: points/award toggle (in case the URL param doesn't stick).
_SEL_POINTS_TOGGLE = "[data-qa='points-toggle'], button:has-text('Points'), [aria-label*='points' i]"
# VERIFY: per-row selectors.
_SEL_DEPART_TIME = "[data-qa='departure-time'], [class*='departTime'], time[class*='depart']"
_SEL_ARRIVE_TIME = "[data-qa='arrival-time'], [class*='arriveTime'], time[class*='arrive']"
_SEL_FLIGHT_NUM = "[data-qa='flight-number'], [class*='flightNumber']"
_SEL_STOPS = "[data-qa='stops'], [class*='stops'], [class*='nonstop']"
# VERIFY: the fare cell for a given cabin (Blue vs Mint) and its points/taxes text.
_SEL_FARE_CELL = "[data-qa='fare-{cabin}'], [class*='{cabin}' i][class*='fare' i], [class*='{cabin}' i][class*='price' i]"
_SEL_POINTS = "[data-qa='points'], [class*='points'], [class*='Points']"
_SEL_TAXES = "[data-qa='taxes'], [class*='taxes'], [class*='fees']"


def signature(page) -> bool:
    """Cheap presence check: are JetBlue's results selectors on the page?"""
    try:
        return page.locator(_SEL_FLIGHT_ROW).count() > 0
    except Exception:
        return False


def _parse_int(text):
    """Extract the first integer from a string like '12,300 pts'."""
    if not text:
        return 0
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def _parse_taxes(text):
    """Extract a dollar amount like '$5.60' -> 5.60."""
    if not text:
        return 0
    kept = "".join(ch for ch in text if ch.isdigit() or ch == ".")
    try:
        return float(kept) if kept else 0
    except ValueError:
        return 0


def _norm_time(text):
    """Normalize '7:00 AM' -> '07:00'; return raw text if unparseable."""
    text = (text or "").strip()
    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return text


def _within_window(depart_hhmm, query):
    """Honor depart_after / depart_before (the ranker handles points filtering)."""
    if not depart_hhmm or ":" not in depart_hhmm:
        return True
    try:
        h, m = depart_hhmm.split(":")[:2]
        t = datetime.strptime(f"{int(h):02d}:{int(m):02d}", "%H:%M").time()
    except (ValueError, IndexError):
        return True
    if query.depart_after and t < query.depart_after:
        return False
    if query.depart_before and t > query.depart_before:
        return False
    return True


def _ensure_points_mode(page):
    """Defensively click the points toggle if the URL param didn't switch the display."""
    try:
        toggle = page.locator(_SEL_POINTS_TOGGLE).first
        if toggle.count() > 0 and toggle.is_visible():
            toggle.click()  # VERIFY: only needed if fares render in cash by default
            human_pause()
    except Exception:
        pass


def _scrape_one(page, origin, dest, d, query, mileage_field, cabin_label):
    """Navigate one date deep link and return raw rows for matching flights."""
    rows = []
    url = _DEEPLINK.format(origin=origin, dest=dest, date=d.isoformat())
    goto(page, url)
    human_pause(1.0, 2.0)
    _ensure_points_mode(page)

    if not signature(page):
        return rows

    flights = page.locator(_SEL_FLIGHT_ROW)
    fare_sel = _SEL_FARE_CELL.format(cabin=cabin_label)
    for i in range(flights.count()):
        try:
            row = flights.nth(i)
            fare = row.locator(fare_sel).first
            if fare.count() == 0:
                continue  # this flight has no award seat in the requested cabin
            points = _parse_int(fare.locator(_SEL_POINTS).first.inner_text())
            if points <= 0:
                continue
            try:
                taxes = _parse_taxes(fare.locator(_SEL_TAXES).first.inner_text())
            except Exception:
                taxes = 0

            depart = _norm_time(row.locator(_SEL_DEPART_TIME).first.inner_text())
            if not _within_window(depart, query):
                continue
            arrive = _norm_time(row.locator(_SEL_ARRIVE_TIME).first.inner_text())

            try:
                flight_num = row.locator(_SEL_FLIGHT_NUM).first.inner_text().strip()
            except Exception:
                flight_num = ""

            try:
                stops_txt = row.locator(_SEL_STOPS).first.inner_text().lower()
                direct = "nonstop" in stops_txt or "non-stop" in stops_txt or "0 stop" in stops_txt
            except Exception:
                direct = False

            rows.append({
                "Source": "jetblue",
                mileage_field: points,
                "TotalTaxes": taxes,
                "Date": d.isoformat(),
                "Direct": direct,
                "OriginAirport": origin,
                "DestinationAirport": dest,
                "FlightNumbers": flight_num,
                "DepartTime": depart,
                "ArriveTime": arrive,
                "DeepLink": url,
            })
        except Exception as e:
            print(f"[jetblue] skipping a flight row: {e}", file=sys.stderr)
            continue
    return rows


def scrape(page, query) -> list:
    """Read TrueBlue points per flight for each date via JetBlue date deep links."""
    try:
        mileage_field, cabin_label = _CABIN_MAP.get(query.cabin, _CABIN_MAP["economy"])

        # SUPPORTS_METRO is True, but if the site only accepts a single airport we use
        # the first of each list. VERIFY: confirm metros are accepted; otherwise the
        # runner should set SUPPORTS_METRO=False and loop airports + merge_dedupe.
        origin = query.origin_airports[0]  # VERIFY: send full metro instead if supported
        dest = query.dest_airports[0]      # VERIFY

        out = []
        for d in query.dates():
            out.extend(_scrape_one(page, origin, dest, d, query,
                                   mileage_field, cabin_label))
            human_pause()
        return out
    except Exception as e:
        print(f"[jetblue] scrape failed: {e}", file=sys.stderr)
        return []
