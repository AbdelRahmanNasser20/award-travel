#!/usr/bin/env python3
"""American Airlines (AAdvantage) award-flight scraper.

Per SKILL.md (ground truth) for American:
  - American shows AAdvantage award availability WITHOUT login.
  - Use the advanced search form at aa.com and check "Redeem miles".
  - Origin "NYC - New York, NY" covers all NY airports (SUPPORTS_METRO = True).
  - Results render a DATE STRIP plus Main / Business / First columns giving
    per-day, per-cabin miles. Read the cheapest per day across query.dates().
  - AA often has nonstops.

Driven with the Playwright SYNC API; `page` is already open. We cannot test
live, so every selector below is a best-effort guess and is marked `# VERIFY`.
On any failure we warn to stderr and return [] so the runner can fall back.
"""
import sys
import re
from datetime import date

from browser.session import human_type, human_pause, goto

SUPPORTS_METRO = True
HOME_URL = "https://www.aa.com"

# Map our cabin names -> raw mileage field + AA results column label. # VERIFY
_CABIN = {
    "economy": ("YMileageCost", "main"),
    "premium": ("WMileageCost", "main"),     # AA folds premium econ into Main on many routes # VERIFY
    "business": ("JMileageCost", "business"),
    "first": ("FMileageCost", "first"),
}

# Search-form selectors. # VERIFY
_SEL_REDEEM_MILES = "input#flightSearchForm\\.tripType\\.redeemMiles, input[name='redeemMiles'], #redeemMiles"  # VERIFY
_SEL_ORIGIN = "#reservationFlightSearchForm\\.originAirport, input#origin, input[name='originAirport']"  # VERIFY
_SEL_DEST = "#reservationFlightSearchForm\\.destinationAirport, input#destination, input[name='destinationAirport']"  # VERIFY
_SEL_ONEWAY = "input#flightSearchForm\\.tripType\\.oneWay, input[value='oneWay']"  # VERIFY
_SEL_DEPART_DATE = "input#aa-leavingOn, input[name='departDate']"  # VERIFY
_SEL_SUBMIT = "#flightSearchForm\\.button\\.reSubmit, button[type='submit'], #flightSearchSubmit"  # VERIFY

# Results selectors. # VERIFY
_SEL_RESULTS_ROOT = ".results-grid, [data-testid='results'], #flightResultsContainer"  # VERIFY
_SEL_FLIGHT_ROW = ".flight-cell, [data-testid='grid-section-flight'], li.flight"  # VERIFY


def signature(page) -> bool:
    """Cheap presence check: are AA's award-results selectors on the page?"""
    try:
        loc = page.locator(_SEL_RESULTS_ROOT)
        if loc.count() > 0:
            return True
        return page.locator(_SEL_FLIGHT_ROW).count() > 0
    except Exception:
        return False


def _fmt_date(d: date) -> str:
    # AA's date input typically wants MM/DD/YYYY. # VERIFY
    return d.strftime("%m/%d/%Y")


def _parse_miles(text: str):
    """'57.5K' / '57,500' / '57.5k miles' -> int miles, or None."""
    if not text:
        return None
    t = text.strip().lower().replace(",", "")
    m = re.search(r"([\d.]+)\s*k", t)
    if m:
        try:
            return int(round(float(m.group(1)) * 1000))
        except ValueError:
            return None
    m = re.search(r"(\d+)", t)
    return int(m.group(1)) if m else None


def _parse_taxes(text: str):
    """'$5.60' / 'USD 11.20' -> float, or 0."""
    if not text:
        return 0
    m = re.search(r"([\d,]+\.?\d*)", text.replace(",", ""))
    try:
        return float(m.group(1)) if m else 0
    except (ValueError, AttributeError):
        return 0


def _norm_time(text: str):
    """'7:00 AM' / '07:00' -> 'HH:MM' 24h, or None."""
    if not text:
        return None
    m = re.search(r"(\d{1,2}):(\d{2})\s*([AaPp][Mm])?", text.strip())
    if not m:
        return None
    hh, mm, ap = int(m.group(1)), m.group(2), m.group(3)
    if ap:
        ap = ap.lower()
        if ap == "pm" and hh != 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
    return f"{hh:02d}:{mm}"


def _in_window(depart_hhmm, query):
    if depart_hhmm is None:
        return True
    parts = depart_hhmm.split(":")
    try:
        from datetime import time as _t
        dt = _t(int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return True
    if query.depart_after and dt < query.depart_after:
        return False
    if query.depart_before and dt > query.depart_before:
        return False
    return True


def _run_search(page, query, origin, dest, d: date):
    """Fill the advanced search form for one O&D + date with Redeem miles on."""
    goto(page, HOME_URL)
    human_pause()

    # Switch to award (Redeem miles) mode. # VERIFY
    try:
        redeem = page.locator(_SEL_REDEEM_MILES).first
        if redeem.count() and not redeem.is_checked():
            redeem.check()
            human_pause()
    except Exception:
        pass

    # One-way. # VERIFY
    try:
        ow = page.locator(_SEL_ONEWAY).first
        if ow.count():
            ow.check()
            human_pause()
    except Exception:
        pass

    human_type(page.locator(_SEL_ORIGIN).first, origin)
    human_pause()
    human_type(page.locator(_SEL_DEST).first, dest)
    human_pause()
    human_type(page.locator(_SEL_DEPART_DATE).first, _fmt_date(d))
    human_pause()

    page.locator(_SEL_SUBMIT).first.click()
    page.wait_for_selector(_SEL_RESULTS_ROOT, timeout=45000)  # VERIFY
    human_pause(1.0, 2.0)


def _scrape_one(page, query, origin, dest, d: date):
    """Read every flight card on the current results page into raw rows."""
    rows = []
    cost_field, col = _CABIN.get(query.cabin, _CABIN["economy"])
    deeplink = page.url

    cards = page.locator(_SEL_FLIGHT_ROW)
    n = cards.count()
    for i in range(n):
        card = cards.nth(i)
        try:
            # Cabin miles cell for this card. # VERIFY
            price_loc = card.locator(
                f"[data-cabin='{col}'] .price, .product.{col} .amount, "
                f".cabin-{col} .miles"
            ).first  # VERIFY
            miles = _parse_miles(price_loc.inner_text()) if price_loc.count() else None
            if not miles:
                continue

            taxes_loc = card.locator(
                f"[data-cabin='{col}'] .taxes, .product.{col} .perPassengerTaxesAndFees"
            ).first  # VERIFY
            taxes = _parse_taxes(taxes_loc.inner_text()) if taxes_loc.count() else 0

            dep_loc = card.locator(".origin .time, [data-testid='depart-time'], .departTime").first  # VERIFY
            arr_loc = card.locator(".destination .time, [data-testid='arrive-time'], .arriveTime").first  # VERIFY
            depart = _norm_time(dep_loc.inner_text()) if dep_loc.count() else None
            arrive = _norm_time(arr_loc.inner_text()) if arr_loc.count() else None

            if not _in_window(depart, query):
                continue

            # Flight number(s). # VERIFY
            fn_loc = card.locator(".flight-number, [data-testid='flight-number'], .carrierFlightNumber")  # VERIFY
            flights = []
            for j in range(fn_loc.count()):
                txt = fn_loc.nth(j).inner_text().strip()
                m = re.search(r"([A-Z]{2})\s*(\d+)", txt)
                if m:
                    flights.append(f"{m.group(1)}{m.group(2)}")
            flight_numbers = ", ".join(flights) if flights else ""

            # Stops -> Direct. # VERIFY
            stops_loc = card.locator(".stops, [data-testid='stops'], .duration .stops").first  # VERIFY
            stops_txt = stops_loc.inner_text().lower() if stops_loc.count() else ""
            direct = ("nonstop" in stops_txt) or ("non-stop" in stops_txt) or ("0 stop" in stops_txt)
            if not stops_txt and len(flights) == 1:
                direct = True

            row = {
                "Source": "american",
                cost_field: int(miles),
                "TotalTaxes": taxes,
                "Date": d.strftime("%Y-%m-%d"),
                "Direct": bool(direct),
                "OriginAirport": origin if len(origin) == 3 else "",
                "DestinationAirport": dest if len(dest) == 3 else "",
                "FlightNumbers": flight_numbers,
                "DepartTime": depart or "",
                "ArriveTime": arrive or "",
                "DeepLink": deeplink,
            }
            rows.append(row)
        except Exception as e:
            print(f"[american] skipped a card: {e}", file=sys.stderr)
            continue
    return rows


def scrape(page, query) -> list:
    """Search AAdvantage award space across query.dates() and return raw rows."""
    out = []
    # SUPPORTS_METRO: send the metro string so AA auto-expands NY airports. # VERIFY
    origin = query.origin_airports[0] if query.origin_airports else ""
    dest = query.dest_airports[0] if query.dest_airports else ""
    if not origin or not dest:
        return out
    try:
        for d in query.dates():
            try:
                _run_search(page, query, origin, dest, d)
                out.extend(_scrape_one(page, query, origin, dest, d))
            except Exception as e:
                print(f"[american] search failed for {d}: {e}", file=sys.stderr)
                continue
    except Exception as e:
        print(f"[american] scrape aborted: {e}", file=sys.stderr)
        return []
    return out
