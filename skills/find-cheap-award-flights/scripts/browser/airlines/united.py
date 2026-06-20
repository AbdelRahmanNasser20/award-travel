#!/usr/bin/env python3
"""United (MileagePlus) award-search scraper — Playwright SYNC API.

Per the skill's SKILL.md United notes (treated as ground truth):
- United REQUIRES sign-in to view miles pricing ("You must be signed-in to see
  flight results with miles"). We drive a real, already-logged-in Chrome profile,
  so we assume logged in and NEVER type a password.
- The "Book with miles" / award toggle must be set BEFORE searching.
- United auto-expands to all NYC airports when origin = "New York", so this module
  sets SUPPORTS_METRO = True and searches the origin airports together.
- The results page exposes a "30-day calendar" link giving cheapest miles per day
  across the range at once — more efficient than one search per date.

Selectors are best-effort from the notes and CANNOT be tested against the live
site here; every guessed selector is marked with a trailing ``# VERIFY`` comment
so it can be tuned on the first real run. Any failure returns [] and warns to
stderr so one airline can never crash the whole run.
"""
import sys
from datetime import datetime

from browser.session import human_type, human_pause, goto

SUPPORTS_METRO = True
HOME_URL = "https://www.united.com"

# cabin -> raw mileage field expected by the shared ranker.
_CABIN_FIELD = {
    "economy": "YMileageCost",
    "premium": "WMileageCost",
    "business": "JMileageCost",
    "first": "FMileageCost",
}

# United's own cabin label used in the booking-class dropdown.
_CABIN_LABEL = {
    "economy": "Economy",
    "premium": "Premium economy",
    "business": "Business",
    "first": "First",
}


def _warn(msg):
    print(f"[united] {msg}", file=sys.stderr)


def _parse_clock(text):
    """Parse '7:00 AM' / '07:00' / '10:30 PM' into a 24h 'HH:MM' string + time obj."""
    if not text:
        return None, None
    t = text.strip().upper().replace(".", "")
    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
        try:
            dt = datetime.strptime(t, fmt)
            return dt.strftime("%H:%M"), dt.time()
        except ValueError:
            continue
    return None, None


def _digits(text):
    """Extract an int from a string like '12.5K miles' / '12,500' (K-suffix aware)."""
    if not text:
        return None
    s = text.strip().lower()
    mult = 1
    if "k" in s:
        mult = 1000
        s = s.split("k")[0]
    s = "".join(c for c in s if c.isdigit() or c == ".")
    if not s:
        return None
    try:
        return int(round(float(s) * mult))
    except ValueError:
        return None


def signature(page) -> bool:
    """Cheap presence check: are United's known result containers on the page?"""
    try:
        for sel in (
            "div[class*='app-components-Shopping-FlightResults']",  # VERIFY results wrapper
            "[data-test='flight-block']",                           # VERIFY one result row
            "div.atm-c-flight-block",                               # VERIFY result card
        ):
            if page.locator(sel).count() > 0:
                return True
        return False
    except Exception:
        return False


def _set_award_toggle(page):
    """Turn on 'Book with miles' BEFORE searching (notes require this)."""
    for sel in (
        "input#bookFlightSearchView_awardTravel",     # VERIFY award radio/checkbox
        "label:has-text('Book with miles')",          # VERIFY award label
        "[data-test='award-travel-toggle']",          # VERIFY award toggle
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.click()
                human_pause()
                return True
        except Exception:
            continue
    _warn("could not confirm 'Book with miles' toggle (VERIFY selectors)")
    return False


def _fill_airport(page, field_selector, value):
    box = page.locator(field_selector).first
    box.click()
    human_pause(0.2, 0.5)
    try:
        box.fill("")
    except Exception:
        pass
    human_type(box, value)
    human_pause()
    # Accept the first autocomplete suggestion (metro expansion happens automatically).
    try:
        opt = page.locator("ul[role='listbox'] li, [role='option']").first  # VERIFY autocomplete
        if opt.count() > 0:
            opt.click()
            human_pause()
    except Exception:
        pass


def scrape(page, query) -> list[dict]:
    """Run one United award search across the date range and read the 30-day
    calendar for cheapest miles per day. Returns raw-shape rows (see contract)."""
    rows: list[dict] = []
    field = _CABIN_FIELD.get(query.cabin, "YMileageCost")
    origin = ",".join(query.origin_airports) or (query.origin_airports[0] if query.origin_airports else "")
    dest = query.dest_airports[0] if query.dest_airports else ""
    wanted_dates = {d.isoformat() for d in query.dates()}

    try:
        goto(page, HOME_URL)
        human_pause()

        # 1) Award pricing BEFORE searching.
        _set_award_toggle(page)

        # 2) One-way trip type (we search a single direction at a time).
        try:
            page.locator("input#bookFlightSearchView_tripTypes_oneway").first.click()  # VERIFY one-way
            human_pause()
        except Exception:
            pass

        # 3) Origin (metro auto-expands) + destination.
        _fill_airport(page, "input#bookFlightOriginInput", origin)        # VERIFY origin input
        _fill_airport(page, "input#bookFlightDestinationInput", dest)     # VERIFY dest input

        # 4) Depart date = range start; the calendar gives us the rest.
        try:
            date_box = page.locator("input#DepartDate").first             # VERIFY depart date input
            human_type(date_box, query.start.strftime("%m/%d/%Y"))
            human_pause()
            page.keyboard.press("Escape")
        except Exception:
            _warn("could not set depart date (VERIFY selector)")

        # 5) Cabin / booking class.
        try:
            cabin_sel = page.locator("select#bookFlightCabinType").first  # VERIFY cabin select
            if cabin_sel.count() > 0:
                cabin_sel.select_option(label=_CABIN_LABEL.get(query.cabin, "Economy"))
                human_pause()
        except Exception:
            pass

        # 6) Search.
        page.locator("button#btn-search, button[type='submit']:has-text('Find flights')").first.click()  # VERIFY search button
        page.wait_for_load_state("domcontentloaded")
        human_pause(1.5, 3.0)

        if not signature(page):
            _warn("results container not detected after search (VERIFY selectors)")

        # 7) Open the 30-day calendar (cheapest miles per day across the range).
        try:
            cal = page.locator(
                "a:has-text('30-day'), button:has-text('Flexible dates'), [data-test='flexible-dates']"  # VERIFY calendar link
            ).first
            if cal.count() > 0:
                cal.click()
                human_pause(1.0, 2.0)
                rows.extend(_read_calendar(page, query, field, origin, dest, wanted_dates))
        except Exception as e:
            _warn(f"30-day calendar unavailable: {e}")

        # 8) Fallback: scrape the visible single-day result list.
        if not rows:
            rows.extend(_read_results(page, query, field, dest))

        return rows
    except Exception as e:
        _warn(f"scrape failed: {e}")
        return []


def _read_calendar(page, query, field, origin, dest, wanted_dates) -> list[dict]:
    """Read per-day cheapest miles from the 30-day flexible-date calendar."""
    out: list[dict] = []
    try:
        cells = page.locator("[data-test='calendar-day'], td.calendar-day, button.bidi-day")  # VERIFY day cell
        for i in range(cells.count()):
            try:
                cell = cells.nth(i)
                day = cell.get_attribute("data-date") or cell.get_attribute("data-test-date")  # VERIFY date attr
                if not day:
                    continue
                day = day[:10]
                if wanted_dates and day not in wanted_dates:
                    continue
                miles = _digits(cell.inner_text())
                if not miles:
                    continue
                out.append({
                    "Source": "united",
                    field: miles,
                    "TotalTaxes": 0,
                    "Date": day,
                    "Direct": False,
                    "OriginAirport": query.origin_airports[0] if query.origin_airports else origin,
                    "DestinationAirport": dest,
                    "FlightNumbers": "",
                    "DepartTime": "",
                    "ArriveTime": "",
                    "DeepLink": page.url,
                })
            except Exception:
                continue
    except Exception as e:
        _warn(f"calendar read failed: {e}")
    return out


def _read_results(page, query, field, dest) -> list[dict]:
    """Scrape the visible single-day result rows as a fallback."""
    out: list[dict] = []
    try:
        cards = page.locator("[data-test='flight-block'], div.atm-c-flight-block")  # VERIFY result row
        for i in range(cards.count()):
            try:
                card = cards.nth(i)

                dep_raw = card.locator("[data-test='flight-time-departure'], .flight-time-departure").first.inner_text()  # VERIFY depart time
                arr_raw = card.locator("[data-test='flight-time-arrival'], .flight-time-arrival").first.inner_text()      # VERIFY arrive time
                depart_str, depart_t = _parse_clock(dep_raw)
                arrive_str, _ = _parse_clock(arr_raw)

                # Respect depart_after / depart_before (leave miles filtering to ranker).
                if depart_t is not None:
                    if query.depart_after and depart_t < query.depart_after:
                        continue
                    if query.depart_before and depart_t > query.depart_before:
                        continue

                miles = _digits(card.locator(
                    "[data-test='miles-amount'], .miles-amount"  # VERIFY miles amount
                ).first.inner_text())
                if not miles:
                    continue

                try:
                    taxes = _digits(card.locator("[data-test='taxes-amount'], .taxes-amount").first.inner_text()) or 0  # VERIFY taxes
                except Exception:
                    taxes = 0

                try:
                    fn = card.locator("[data-test='flight-number'], .flight-number").first.inner_text().strip()  # VERIFY flight number
                except Exception:
                    fn = ""

                try:
                    stops_txt = card.locator("[data-test='stops'], .stops-text").first.inner_text().lower()  # VERIFY stops label
                    direct = "nonstop" in stops_txt or "non-stop" in stops_txt or "0 stop" in stops_txt
                except Exception:
                    direct = False

                try:
                    origin_code = card.locator("[data-test='origin-code'], .origin-code").first.inner_text().strip()  # VERIFY origin code
                except Exception:
                    origin_code = query.origin_airports[0] if query.origin_airports else ""

                out.append({
                    "Source": "united",
                    field: miles,
                    "TotalTaxes": taxes,
                    "Date": query.start.isoformat(),
                    "Direct": direct,
                    "OriginAirport": origin_code,
                    "DestinationAirport": dest,
                    "FlightNumbers": fn,
                    "DepartTime": depart_str or "",
                    "ArriveTime": arrive_str or "",
                    "DeepLink": page.url,
                })
            except Exception:
                continue
    except Exception as e:
        _warn(f"results read failed: {e}")
    return out
