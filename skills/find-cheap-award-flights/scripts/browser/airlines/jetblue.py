#!/usr/bin/env python3
"""JetBlue (TrueBlue points) award-flight scraper — Playwright SYNC API.

Per SKILL.md: "JetBlue shows points WITHOUT login via the date deep links — fastest."

VERIFIED against the live site (2026-06): JetBlue's booking results are an Angular app
using the Auro / `cb-*` component set. The date deep link below lands directly on the
"Select Flights" results page in points mode. Structure:
  cb-flight-result-item                       one flight option (a row)
    cb-itinerary-panel  -> innerText like:    "Nonstop | 5h 41m | 7:18pm | JFK | 9:59pm | PHX | JetBlue B6 135"
    .cb-bundle-price__price -> "46,800 pts"   one per fare bundle (we take the cheapest)

We parse the itinerary panel text (robust to class churn) and take the minimum bundle
price as the cabin's points. Failures return [] with a stderr warning.
"""
import re
import sys
from datetime import datetime

from browser.session import human_pause, goto

SUPPORTS_METRO = True   # scrape() loops every origin/dest airport, covering a metro.
HOME_URL = "https://www.jetblue.com"

_CABIN_FIELD = {"economy": "YMileageCost", "premium": "YMileageCost",
                "business": "JMileageCost", "first": "JMileageCost"}

_DEEPLINK = (
    HOME_URL + "/booking/flights"
    "?from={origin}&to={dest}&depart={date}"
    "&isMultiCity=false&noOfRoute=1&lang=en"
    "&adults=1&children=0&infants=0"
    "&sharedMarket=false&roundTripFaresFlag=false&usePoints=true"
)

_SEL_ROW = "cb-flight-result-item"            # VERIFIED
_SEL_PRICE = ".cb-bundle-price__price"        # VERIFIED ("46,800 pts")
_SEL_PANEL = "cb-itinerary-panel"             # VERIFIED (pipe-joined itinerary text)

_TIME_RE = re.compile(r"\d{1,2}:\d{2}\s*[ap]m", re.I)
_PTS_RE = re.compile(r"([\d,]+)\s*(?:pts|points)", re.I)
_FLT_RE = re.compile(r"\bB6\s*(\d{1,4})\b", re.I)
_CODE_RE = re.compile(r"\b[A-Z]{3}\b")


def signature(page) -> bool:
    try:
        return page.locator(_SEL_ROW).count() > 0
    except Exception:
        return False


def _norm_time(text):
    text = (text or "").strip().replace(" ", "")
    for fmt in ("%I:%M%p", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return text


def _within_window(hhmm, query):
    if not hhmm or ":" not in hhmm:
        return True
    try:
        h, m = hhmm.split(":")[:2]
        t = datetime.strptime(f"{int(h):02d}:{int(m):02d}", "%H:%M").time()
    except (ValueError, IndexError):
        return True
    if query.depart_after and t < query.depart_after:
        return False
    if query.depart_before and t > query.depart_before:
        return False
    return True


def _scrape_one(page, origin, dest, d, query, field):
    rows = []
    url = _DEEPLINK.format(origin=origin, dest=dest, date=d.isoformat())
    goto(page, url)
    try:
        page.wait_for_selector(_SEL_ROW, timeout=25000)
    except Exception:
        return rows  # no results for this date/route, or page didn't render
    # Wait until the flight list stops growing (results stream in via XHR), scrolling
    # to trigger lazy rendering, so we read ALL flights and the true cheapest.
    last, stable = -1, 0
    for _ in range(12):
        try:
            page.mouse.wheel(0, 6000)
        except Exception:
            pass
        human_pause(0.8, 1.3)
        cur = page.locator(_SEL_ROW).count()
        stable = stable + 1 if cur == last else 0
        last = cur
        if stable >= 2 and cur > 0:
            break

    items = page.locator(_SEL_ROW)
    for i in range(items.count()):
        try:
            item = items.nth(i)
            try:
                panel = item.locator(_SEL_PANEL).first.inner_text()
            except Exception:
                panel = item.inner_text()
            panel_flat = " ".join(panel.split())

            prices = [int(m.replace(",", "")) for m in _PTS_RE.findall(panel_flat)]
            cell_prices = []
            cells = item.locator(_SEL_PRICE)
            for j in range(cells.count()):
                mm = _PTS_RE.search(cells.nth(j).inner_text())
                if mm:
                    cell_prices.append(int(mm.group(1).replace(",", "")))
            allp = [p for p in (cell_prices or prices) if p > 0]
            if not allp:
                continue
            points = min(allp)

            times = _TIME_RE.findall(panel_flat)
            depart = _norm_time(times[0]) if times else ""
            arrive = _norm_time(times[1]) if len(times) > 1 else ""
            if not _within_window(depart, query):
                continue

            fm = _FLT_RE.search(panel_flat)
            flight_num = f"B6{fm.group(1)}" if fm else ""
            codes = _CODE_RE.findall(panel_flat)
            o_code = codes[0] if codes else origin
            d_code = codes[-1] if codes else dest
            direct = "nonstop" in panel_flat.lower()

            rows.append({
                "Source": "jetblue", field: points, "TotalTaxes": None,
                "Date": d.isoformat(), "Direct": direct,
                "OriginAirport": o_code, "DestinationAirport": d_code,
                "FlightNumbers": flight_num, "DepartTime": depart, "ArriveTime": arrive,
                "DeepLink": url,
            })
        except Exception as e:
            print(f"[jetblue] skipping a row: {e}", file=sys.stderr)
    return rows


def scrape(page, query) -> list:
    try:
        field = _CABIN_FIELD.get(query.cabin, "YMileageCost")
        out = []
        for origin in query.origin_airports:
            for dest in query.dest_airports:
                for d in query.dates():
                    out.extend(_scrape_one(page, origin, dest, d, query, field))
                    human_pause()
        return out
    except Exception as e:
        print(f"[jetblue] scrape failed: {e}", file=sys.stderr)
        return []
