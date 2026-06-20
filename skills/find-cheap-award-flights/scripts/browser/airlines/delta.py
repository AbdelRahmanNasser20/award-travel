#!/usr/bin/env python3
"""Delta (SkyMiles) award-flight scraper — Playwright SYNC API.

Hard-won notes from SKILL.md (follow these; they were paid for in timeouts):

  * Delta shows SkyMiles pricing WITHOUT login, but the homepage CONSTANTLY
    POLLS THE NETWORK. Waiting for "networkidle" therefore NEVER settles and
    times out. Always navigate with wait_until="domcontentloaded" (the provided
    `goto` helper does exactly this) and never wait on networkidle.

  * Toggle "Shop with Miles" so prices come back in miles, not dollars.

  * Build the search with ELEMENT REFS (locators / get_by_role), NOT pixel
    coordinates — the homepage layout reflows and any captured coordinate drifts.

  * Order: trip type (one-way) -> origin (NYC) -> destination -> date.
    With "My Dates are Flexible" ON you MUST actually click a day in the
    calendar before "Done"; a stray "Done" with no day selected silently
    clears the date and the form errors out with "Date is Required".

  * Click "Find Flights". This navigates to /flightsearch/flexible-dates,
    a results page that — unlike the homepage — DOES settle and is readable.
    The flexible-dates strip shows lowest miles for ~7 days around the date.
    On that page toggle "Show Price In: Miles" and "Non Stop / All Flights".

  * Delta domestic economy is dynamically priced and often eye-wateringly
    high. That is expected; we hand miles filtering to the ranker.

Best-effort selectors only — this could not be tested against the live site, so
every selector guess is marked `# VERIFY`. Any failure returns [] and warns on
stderr rather than raising.
"""
import re
import sys
import traceback

from browser.session import human_pause, human_type, goto

SUPPORTS_METRO = True
HOME_URL = "https://www.delta.com"

# Delta's flexible-dates results page; signature() also accepts the homepage form.
_RESULTS_URL_FRAG = "flightsearch/flexible-dates"  # VERIFY

_CABIN_FIELD = {
    "economy": "YMileageCost",
    "premium": "WMileageCost",
    "business": "JMileageCost",
    "first": "FMileageCost",
}


def _warn(msg):
    print(f"[delta] {msg}", file=sys.stderr)


def _to_24h(text):
    """Normalize times like '7:05 a.m.' / '10:30 PM' -> 'HH:MM' (24h). None on miss."""
    if not text:
        return None
    t = text.strip().lower().replace(".", "").replace(" ", "")
    m = re.match(r"(\d{1,2}):(\d{2})(am|pm)?", t)
    if not m:
        return None
    hh, mm, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    if ap == "pm" and hh != 12:
        hh += 12
    elif ap == "am" and hh == 12:
        hh = 0
    return f"{hh:02d}:{mm:02d}"


def _to_int(text):
    if text is None:
        return None
    digits = re.sub(r"[^\d]", "", str(text))
    return int(digits) if digits else None


def _within_window(depart_hhmm, query):
    """Respect depart_after / depart_before; leave miles to the ranker."""
    if not depart_hhmm:
        return True
    try:
        from datetime import time as _t
        h, m = (int(x) for x in depart_hhmm.split(":"))
        dt = _t(h, m)
    except Exception:
        return True
    if query.depart_after and dt < query.depart_after:
        return False
    if query.depart_before and dt > query.depart_before:
        return False
    return True


def signature(page) -> bool:
    """Cheap presence check: are we on a Delta results/search surface we can read?"""
    try:
        url = (page.url or "").lower()
        if _RESULTS_URL_FRAG in url:
            return True
        # Flexible-dates strip or the results list container.  # VERIFY
        loc = page.locator(
            "[data-testid='flexible-dates-strip'], .flexible-dates, "
            "[class*='flexLowFareCal'], [class*='flight-result']"
        )
        if loc.count() > 0:
            return True
        # Fall back to recognizing the homepage search form.  # VERIFY
        return page.get_by_role("button", name=re.compile("find flights", re.I)).count() > 0
    except Exception:
        return False


def _toggle_shop_with_miles(page):
    """Flip 'Shop with Miles' on the homepage so fares price in miles."""
    try:
        # Usually a checkbox/switch labelled "Shop with Miles".  # VERIFY
        cb = page.get_by_label(re.compile("shop with miles", re.I))
        if cb.count() == 0:
            cb = page.get_by_role("checkbox", name=re.compile("shop with miles", re.I))
        if cb.count() > 0 and not cb.first.is_checked():
            cb.first.check()
            human_pause()
    except Exception as e:
        _warn(f"shop-with-miles toggle skipped: {e}")


def _set_oneway(page):
    try:
        # Trip-type selector; one-way radio/option.  # VERIFY
        ow = page.get_by_role("radio", name=re.compile("one.?way", re.I))
        if ow.count() == 0:
            ow = page.get_by_text(re.compile(r"^\s*one.?way\s*$", re.I))
        if ow.count() > 0:
            ow.first.click()
            human_pause()
    except Exception as e:
        _warn(f"one-way select skipped: {e}")


def _fill_airport(page, kind, code):
    """kind: 'from'|'to'. Open the field, type the code, pick the first suggestion."""
    label = "from" if kind == "from" else "to"
    # Origin/destination open buttons on the homepage.  # VERIFY
    opener = page.get_by_role(
        "button", name=re.compile(rf"\b{label}\b.*(airport|city)|{label}", re.I)
    )
    if opener.count() == 0:
        opener = page.locator(f"#{label}AirportName, [aria-label*='{label}']")  # VERIFY
    opener.first.click()
    human_pause()
    # The text input that appears in the airport modal.  # VERIFY
    box = page.get_by_role("textbox", name=re.compile(rf"{label}|search", re.I))
    if box.count() == 0:
        box = page.locator("input[aria-label*='Search'], input[type='text']").first
    human_type(box.first if hasattr(box, "first") else box, code)
    human_pause(0.6, 1.2)
    # First matching suggestion in the dropdown.  # VERIFY
    sug = page.get_by_role("option", name=re.compile(code, re.I))
    if sug.count() == 0:
        sug = page.locator(f"[class*='airport'] >> text=/{code}/i")
    sug.first.click()
    human_pause()


def _set_date(page, d):
    """Open the date picker, ensure flexible dates ON, and CLICK a real day."""
    try:
        opener = page.get_by_role(
            "button", name=re.compile("depart|date|calendar", re.I)
        )  # VERIFY
        if opener.count() > 0:
            opener.first.click()
            human_pause()
        # "My Dates are Flexible" toggle — must be ON, but a day must be clicked.  # VERIFY
        flex = page.get_by_text(re.compile("my dates are flexible", re.I))
        if flex.count() > 0:
            try:
                if not flex.first.is_checked():
                    flex.first.check()
            except Exception:
                flex.first.click()
            human_pause()
        # Click the actual calendar cell. aria-label commonly the full date.  # VERIFY
        iso = d.strftime("%Y-%m-%d")
        pretty = d.strftime("%A, %B %-d, %Y") if sys.platform != "win32" else d.strftime("%A, %B %d, %Y")
        cell = page.locator(f"[data-date='{iso}']")
        if cell.count() == 0:
            cell = page.get_by_role("button", name=re.compile(re.escape(pretty), re.I))
        if cell.count() == 0:
            cell = page.get_by_label(re.compile(re.escape(pretty), re.I))
        cell.first.click()  # CRITICAL: select a day or "Done" clears the date.
        human_pause()
        done = page.get_by_role("button", name=re.compile(r"^\s*done\s*$", re.I))  # VERIFY
        if done.count() > 0:
            done.first.click()
            human_pause()
    except Exception as e:
        _warn(f"date select issue ({d}): {e}")


def _find_flights(page):
    btn = page.get_by_role("button", name=re.compile("find flights", re.I))  # VERIFY
    if btn.count() == 0:
        btn = page.get_by_role("button", name=re.compile("search", re.I))
    btn.first.click()
    # Results page settles (unlike the polling homepage); wait for the URL/strip.
    try:
        page.wait_for_url(re.compile(_RESULTS_URL_FRAG), timeout=45000)
    except Exception:
        pass
    human_pause(1.5, 3.0)


def _toggle_results_filters(page):
    """On the results page: price in Miles + Non-Stop only."""
    try:
        miles = page.get_by_role("radio", name=re.compile("miles", re.I))  # VERIFY
        if miles.count() == 0:
            miles = page.get_by_text(re.compile(r"show price in.*miles", re.I))
        if miles.count() > 0:
            miles.first.click()
            human_pause()
    except Exception as e:
        _warn(f"miles toggle skipped: {e}")
    try:
        nonstop = page.get_by_role("radio", name=re.compile("non.?stop", re.I))  # VERIFY
        if nonstop.count() == 0:
            nonstop = page.get_by_text(re.compile("non.?stop", re.I))
        if nonstop.count() > 0:
            nonstop.first.click()
            human_pause()
    except Exception as e:
        _warn(f"non-stop toggle skipped: {e}")


def _parse_results(page, origin, dest, query):
    """Read the flight-result rows on the flexible-dates page into raw rows."""
    rows = []
    field = _CABIN_FIELD.get(query.cabin, "YMileageCost")
    # Each flight result card / row.  # VERIFY
    cards = page.locator("[data-testid='flight-result'], [class*='flight-result'], li[class*='result']")
    n = cards.count()
    for i in range(n):
        try:
            card = cards.nth(i)
            txt = card.inner_text()

            # Times: first two HH:MM-ish tokens are depart / arrive.  # VERIFY
            times = re.findall(r"\d{1,2}:\d{2}\s*[ap]\.?m\.?", txt, re.I)
            depart = _to_24h(times[0]) if len(times) >= 1 else None
            arrive = _to_24h(times[1]) if len(times) >= 2 else None
            if not _within_window(depart, query):
                continue

            # Miles.  # VERIFY
            mil = None
            mloc = card.locator("[class*='miles'], [data-testid*='miles']")
            if mloc.count() > 0:
                mil = _to_int(mloc.first.inner_text())
            if mil is None:
                mm = re.search(r"([\d,]{3,})\s*miles", txt, re.I)
                mil = _to_int(mm.group(1)) if mm else None

            # Taxes / fees (e.g. "$5.60").  # VERIFY
            taxes = 0
            tx = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", txt)
            if tx:
                try:
                    taxes = float(tx.group(1).replace(",", ""))
                except ValueError:
                    taxes = 0

            # Flight number(s) like "DL1234".  # VERIFY
            fns = re.findall(r"\bDL\s?\d{1,4}\b", txt, re.I)
            flight_numbers = ",".join(f.replace(" ", "").upper() for f in fns) or ""

            # Direct if exactly one segment / "Nonstop" present.  # VERIFY
            direct = bool(re.search(r"non.?stop", txt, re.I)) or len(fns) <= 1

            if mil is None:
                continue

            rows.append({
                "Source": "delta",
                field: int(mil),
                "TotalTaxes": taxes,
                "Date": query._cur_date,  # set by scrape() per-date
                "Direct": direct,
                "OriginAirport": origin,
                "DestinationAirport": dest,
                "FlightNumbers": flight_numbers,
                "DepartTime": depart or "",
                "ArriveTime": arrive or "",
                "DeepLink": page.url,
            })
        except Exception as e:
            _warn(f"row parse skipped: {e}")
            continue
    return rows


def _search_one(page, origin, dest, d, query):
    goto(page, HOME_URL)
    _toggle_shop_with_miles(page)
    _set_oneway(page)
    _fill_airport(page, "from", origin)
    _fill_airport(page, "to", dest)
    _set_date(page, d)
    _find_flights(page)
    _toggle_results_filters(page)
    query._cur_date = d.strftime("%Y-%m-%d")
    return _parse_results(page, origin, dest, query)


def scrape(page, query) -> list[dict]:
    """Search Delta SkyMiles award space for every date/route pair in `query`.

    SUPPORTS_METRO is True, so origin_airports may hold several airports; Delta's
    NYC metro handles the grouping, but we loop origins/dests/dates defensively.
    """
    out = []
    try:
        for d in query.dates():
            for origin in query.origin_airports:
                for dest in query.dest_airports:
                    try:
                        out.extend(_search_one(page, origin, dest, d, query))
                    except Exception as e:
                        _warn(f"search failed {origin}->{dest} {d}: {e}")
                        continue
        return out
    except Exception:
        _warn("scrape failed:\n" + traceback.format_exc())
        return []
