#!/usr/bin/env python3
"""Metro/airport handling + the Query shape shared by every scraper.

Some airlines (United, American) accept a metro and auto-expand to nearby airports;
others (Southwest, Frontier) only search one airport at a time, so the runner loops
each airport and de-dupes the pooled results with `merge_dedupe`.
"""
from dataclasses import dataclass, field
from datetime import date, time
from typing import List, Optional, Set

# Extensible metro -> member airports map.
METROS = {
    "NYC": ["JFK", "LGA", "EWR"],
    "NEW YORK": ["JFK", "LGA", "EWR"],
    "DC": ["DCA", "IAD", "BWI"],
    "WAS": ["DCA", "IAD", "BWI"],
    "WASHINGTON": ["DCA", "IAD", "BWI"],
    "CHI": ["ORD", "MDW"],
    "CHICAGO": ["ORD", "MDW"],
    "LA": ["LAX", "BUR", "LGB", "SNA", "ONT"],
    "LON": ["LHR", "LGW", "STN", "LCY"],
    "BAY": ["SFO", "OAK", "SJC"],
    "SF": ["SFO", "OAK", "SJC"],
}

_COST_FIELDS = ("YMileageCost", "WMileageCost", "JMileageCost", "FMileageCost")


def expand(code: str) -> List[str]:
    """Resolve a metro or comma list to individual airport codes; plain codes pass through."""
    code = (code or "").strip().upper()
    if not code:
        return []
    if "," in code:
        out: List[str] = []
        for part in code.split(","):
            for c in expand(part):
                if c not in out:
                    out.append(c)
        return out
    if code in METROS:
        return list(METROS[code])
    return [code]


def _min_cost(row: dict) -> float:
    vals = []
    for f in _COST_FIELDS:
        v = row.get(f)
        try:
            v = int(v)
        except (TypeError, ValueError):
            continue
        if v > 0:
            vals.append(v)
    return min(vals) if vals else float("inf")


def merge_dedupe(rows: List[dict]) -> List[dict]:
    """Collapse duplicate flights (from per-airport loops), keeping the cheapest."""
    best = {}
    for r in rows:
        key = (r.get("Source"), r.get("Date"), r.get("FlightNumbers"), r.get("OriginAirport"))
        if key not in best or _min_cost(r) < _min_cost(best[key]):
            best[key] = r
    return list(best.values())


@dataclass
class Query:
    """A single search across a day range, resolved to concrete airports."""
    origin_airports: List[str]
    dest_airports: List[str]
    start: date
    end: date
    cabin: str = "economy"
    weekdays: Set[int] = field(default_factory=set)   # {} = any; uses WEEKDAY_NUM ints
    max_miles: int = 0
    depart_after: Optional[time] = None
    depart_before: Optional[time] = None

    def dates(self) -> List[date]:
        """Every date in [start, end] (inclusive), honoring the weekday filter."""
        out = []
        d = self.start
        while d <= self.end:
            if not self.weekdays or d.weekday() in self.weekdays:
                out.append(d)
            d = d.fromordinal(d.toordinal() + 1)
        return out
