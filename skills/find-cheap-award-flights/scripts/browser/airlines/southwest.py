#!/usr/bin/env python3
"""Southwest (Rapid Rewards points) award scraper — Playwright SYNC API.

Southwest blocks direct results deep links (they bounce to the form), so we drive
the homepage booking form (VERIFIED live 2026-06, not bot-blocked):
  #originationAirportCode / #destinationAirportCode  airport inputs
  #departureDate  (MM/DD)                            depart date
  input[name=fareType] (Points radio)               points vs dollars
  #flightBookingSubmit                               "Search flights"
then submit and land on /air/booking/select.html results.

We navigate to the results page and LLM-extract the points rows per date (results DOM
is volatile; the LLM is robust).

KNOWN LIMITATION (observed live 2026-06): Southwest aggressively resists automation —
even with the form pre-filled and airport fields confirmed via keyboard, the search
submit stays on "Book a Flight" (validation/bot defense) and never renders results.
Southwest is one of the hardest carriers to automate; treat this scraper as best-effort.
Use seats.aero (cached) for reliable Southwest award coverage.

SUPPORTS_METRO=False: the runner loops each airport, so origin_search() is one code.
"""
import sys

from browser.session import human_pause, goto
from browser import llm_extract

SUPPORTS_METRO = False
HOME_URL = "https://www.southwest.com/"

# VERIFIED: the booking form pre-fills cleanly from query params (orig/dest/date/POINTS/
# one-way all set), so we skip fighting the custom trip-type/fare controls and just submit.
_PREFILL = (HOME_URL + "air/booking/?adultPassengersCount=1&departureDate={date}"
            "&fareType=POINTS&originationAirportCode={origin}&destinationAirportCode={dest}"
            "&tripType=oneway&returnDate=")
_SEL_SUBMIT = "#flightBookingSubmit"             # VERIFIED
_SEL_RESULTS = "[class*='air-booking-select'], [class*='flight-stops'], [class*='fare-button']"  # VERIFY


def signature(page) -> bool:
    try:
        return page.locator(_SEL_RESULTS).count() > 0
    except Exception:
        return False


def scrape(page, query) -> list:
    """Pre-fill the form via URL params, submit, then LLM-extract the results page."""
    out = []
    try:
        origin = query.origin_search()
        dest = query.dest_search()
        for d in query.dates():
            goto(page, _PREFILL.format(date=d.isoformat(), origin=origin, dest=dest))
            human_pause(1.5, 2.5)
            try:
                page.locator(_SEL_SUBMIT).first.click()
            except Exception as e:
                print(f"[southwest] submit failed: {e}", file=sys.stderr)
                continue
            try:
                page.wait_for_selector(_SEL_RESULTS, timeout=30000)
                human_pause(1.5, 2.5)
            except Exception:
                print(f"[southwest] results did not render for {d}", file=sys.stderr)
                continue
            # Extract this date's rows via the LLM (results DOM is volatile), stamping
            # the known date/route so it's correct regardless of what the LLM infers.
            for r in llm_extract.extract_from_page(page, query, "southwest"):
                r["Date"] = d.isoformat()
                r.setdefault("OriginAirport", origin)
                r.setdefault("DestinationAirport", dest)
                r["DeepLink"] = page.url
                out.append(r)
        return out
    except Exception as e:
        print(f"[southwest] scrape failed: {e}", file=sys.stderr)
        return out
