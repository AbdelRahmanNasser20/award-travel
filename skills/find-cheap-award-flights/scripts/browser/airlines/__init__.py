"""
Per-airline scrapers. Each module exposes the same contract:

    SUPPORTS_METRO: bool      # True  -> one search covers nearby airports (site auto-expands)
                              # False -> runner loops each airport, then airports.merge_dedupe
    HOME_URL: str             # award-search entry point
    scrape(page, query) -> list[dict]   # raw-shape rows (see award_common docstring)
    signature(page) -> bool   # are the known result selectors present? (Phase 2 fallback trigger)

`query` is a browser.airports.Query. Rows must use the raw Seats.aero key shape so
they flow through award_common.rank/build_table unchanged.
"""

from importlib import import_module

AIRLINES = ["united", "american", "delta", "southwest", "jetblue", "frontier"]


def get(name):
    """Return the scraper module for an airline name (e.g. 'united')."""
    return import_module(f"{__name__}.{name}")
