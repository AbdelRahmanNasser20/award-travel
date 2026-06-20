#!/usr/bin/env python3
"""Frontier (Frontier Miles) award-flight scraper — Playwright SYNC API.

VERIFIED live (2026-06): flyfrontier.com homepage has a clean booking form (not
bot-blocked):
  #origin / #destination        airport inputs (autocomplete)
  #departureDate                depart date
  input[name=searchType]:
     #searchDollars / #searchPoints   cash vs Frontier Miles (we pick Points)
then the search submits to Frontier's Navitaire booking engine results page.

We drive the form, submit, and LLM-extract the miles rows per date (Navitaire DOM is
volatile; the LLM is robust). Needs GROQ_API_KEY; otherwise reports 0 for Frontier.

KNOWN LIMITATION (observed live 2026-06): Frontier's Search button stays DISABLED until
the form passes its own validation (origin/dest autocomplete confirmed + a real
datepicker day selected). Automated field entry doesn't reliably satisfy this, so the
submit often can't fire. Best-effort; use seats.aero (cached) for reliable Frontier.

SUPPORTS_METRO=False: the runner loops each airport, so origin_search() is one code.
"""
import sys

from browser.session import human_pause, goto
from browser import llm_extract

SUPPORTS_METRO = False
HOME_URL = "https://www.flyfrontier.com/"

_SEL_ORIGIN = "#origin"            # VERIFIED
_SEL_DEST = "#destination"         # VERIFIED
_SEL_DATE = "#departureDate"       # VERIFIED
_SEL_POINTS = "#searchPoints"      # VERIFIED (name=searchType)
_SEL_SUBMIT = "button[type='submit'], button:has-text('Search'), #searchButton"  # VERIFY
# Navitaire results land on a booking.flyfrontier.com URL; detect either the host or rows.
_SEL_RESULTS = "[class*='journey'], [class*='fare'], [class*='flight'], [class*='result']"  # VERIFY


def signature(page) -> bool:
    try:
        return "booking" in page.url or page.locator(_SEL_RESULTS).count() > 0
    except Exception:
        return False


def _select_points(page):
    try:
        pts = page.locator(_SEL_POINTS).first
        if pts.count():
            pts.check(force=True)
            human_pause()
    except Exception as e:
        print(f"[frontier] points toggle failed: {e}", file=sys.stderr)


def _fill_airport(page, sel, code):
    box = page.locator(sel).first
    box.click()
    for _ in range(4):
        box.press("Backspace")
    for ch in code:
        box.type(ch, delay=120)
    human_pause(0.8, 1.4)
    try:
        opt = page.locator("[role='option'], li.ui-menu-item, .typeahead__item").first
        if opt.count() > 0 and opt.is_visible():
            opt.click()
        else:
            box.press("ArrowDown"); box.press("Enter")
    except Exception:
        try:
            box.press("Enter")
        except Exception:
            pass
    human_pause()


def scrape(page, query) -> list:
    out = []
    try:
        origin = query.origin_search()
        dest = query.dest_search()
        for d in query.dates():
            goto(page, HOME_URL)
            human_pause(1.2, 2.0)
            _select_points(page)
            _fill_airport(page, _SEL_ORIGIN, origin)
            _fill_airport(page, _SEL_DEST, dest)
            try:
                box = page.locator(_SEL_DATE).first
                box.click()
                box.fill(d.strftime("%m/%d/%Y"))
                human_pause()
                # close any datepicker overlay
                page.keyboard.press("Escape")
            except Exception as e:
                print(f"[frontier] date fill failed: {e}", file=sys.stderr)
            try:
                page.locator(_SEL_SUBMIT).first.click()
            except Exception as e:
                print(f"[frontier] submit failed: {e}", file=sys.stderr)
                continue
            try:
                page.wait_for_selector(_SEL_RESULTS, timeout=30000)
                human_pause(2.0, 3.0)
            except Exception:
                print(f"[frontier] results did not render for {d}", file=sys.stderr)
                continue
            for r in llm_extract.extract_from_page(page, query, "frontier"):
                r["Date"] = d.isoformat()
                r.setdefault("OriginAirport", origin)
                r.setdefault("DestinationAirport", dest)
                r["DeepLink"] = page.url
                out.append(r)
        return out
    except Exception as e:
        print(f"[frontier] scrape failed: {e}", file=sys.stderr)
        return out
