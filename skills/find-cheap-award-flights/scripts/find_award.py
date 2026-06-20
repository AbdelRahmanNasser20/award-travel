#!/usr/bin/env python3
"""
Live award-flight tool — drives your real, logged-in Chrome to read miles prices
off the airline sites, across a flexible day range, with favorites you can reload.

Subcommands:
  search    find cheapest award space for a route + day range across airlines
  favorite  save a flight from the last search (data + screenshot + page HTML)
  list      list saved favorites with last-checked miles
  refresh   reopen favorite(s) in real Chrome and re-verify current miles
  serve     launch the local web app (Phase 3)

Cached (seats.aero) discovery still lives in search_seats_aero.py; this is the
real-time "Live" path. Shared ranking/report logic comes from award_common.
"""
import argparse
import datetime as dt
import json
import os
import sys

from award_common import WEEKDAY_NUM, build_table, rank, write_report
from browser import airports
from browser.airports import Query

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Load scripts/.env so SEATS_AERO_API_KEY / GROQ_API_KEY / AWARD_CHROME_PROFILE are
# picked up automatically (no-op if python-dotenv isn't installed).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(SCRIPT_DIR, ".env"))
except Exception:
    pass

REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports")
FAVORITES_DIR = os.path.join(SCRIPT_DIR, "favorites")
STATE_FILE = os.path.join(REPORTS_DIR, ".last_search.json")

DEFAULT_AIRLINES = ["united", "american", "jetblue", "southwest", "frontier", "delta"]


# ---------- small parsers ----------
def parse_weekdays(s):
    return {WEEKDAY_NUM[w.strip().title()[:3]] for w in (s or "").split(",") if w.strip()}


def parse_time(s):
    if not s:
        return None
    h, m = s.split(":")
    return dt.time(int(h), int(m))


def parse_date(s):
    return dt.date.fromisoformat(s)


def row_fid(r):
    """Stable id for a result row (used by favorite --id and dedupe)."""
    parts = [r.get("program", "?"), r.get("FlightNumbers", "?"),
             r.get("date", "?"), r.get("OriginAirport", "?")]
    return "_".join(str(p) for p in parts).replace("/", "-").replace(" ", "")


def _depart_min(r):
    t = r.get("DepartTime")
    if not t:
        return None
    try:
        h, m = str(t)[:5].split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def filter_time(rows, after, before):
    if not after and not before:
        return rows
    lo = after.hour * 60 + after.minute if after else None
    hi = before.hour * 60 + before.minute if before else None
    out = []
    for r in rows:
        mins = _depart_min(r)
        if mins is None:          # unknown depart time -> keep (don't hide it)
            out.append(r)
            continue
        if lo is not None and mins < lo:
            continue
        if hi is not None and mins > hi:
            continue
        out.append(r)
    return out


def _llm_fallback(page, query, airline):
    """When deterministic selectors find nothing, try the Groq extraction fallback
    (no-op unless GROQ_API_KEY is set)."""
    try:
        from browser import llm_extract
        if llm_extract.enabled():
            return llm_extract.extract_from_page(page, query, airline)
    except Exception as e:
        print(f"[{airline}] llm fallback error: {e}", file=sys.stderr)
    return []


# ---------- core search (reused by the web app) ----------
def run_search(*, origin, dest, start, end, cabin, airlines, weekdays="",
               max_miles=0, after=None, before=None, headless=False):
    """Scrape each airline over the day range; return ranked rows (with extras)."""
    from browser import session
    from browser import airlines as airpkg

    o_codes = airports.expand(origin)
    d_codes = airports.expand(dest)
    wd = parse_weekdays(weekdays) if isinstance(weekdays, str) else (weekdays or set())
    after_t = parse_time(after) if isinstance(after, str) else after
    before_t = parse_time(before) if isinstance(before, str) else before

    pooled = []
    with session.open_context(headless=headless) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for name in airlines:
            try:
                mod = airpkg.get(name)
            except Exception as e:
                print(f"[{name}] no scraper module: {e}", file=sys.stderr)
                continue
            try:
                if getattr(mod, "SUPPORTS_METRO", False):
                    q = Query(o_codes, d_codes, start, end, cabin, wd, max_miles, after_t, before_t,
                              origin_raw=origin, dest_raw=dest)
                    rows = mod.scrape(page, q) or []
                    rows = rows or _llm_fallback(page, q, name)
                else:  # one airport at a time, then de-dupe
                    rows = []
                    for code in o_codes:
                        q = Query([code], d_codes, start, end, cabin, wd, max_miles, after_t, before_t,
                                  origin_raw=code, dest_raw=dest)
                        got = mod.scrape(page, q) or []
                        rows.extend(got or _llm_fallback(page, q, name))
                    rows = airports.merge_dedupe(rows)
                print(f"[{name}] {len(rows)} rows", file=sys.stderr)
                pooled.extend(rows)
            except Exception as e:
                print(f"[{name}] failed: {e}", file=sys.stderr)

    ranked = rank(pooled, cabin, wd, max_miles)
    ranked = filter_time(ranked, after_t, before_t)
    for r in ranked:
        r["fid"] = row_fid(r)
    return ranked


def _save_state(rows, origin, dest, cabin):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump({"origin": origin, "dest": dest, "cabin": cabin,
                   "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
                   "rows": rows}, f, indent=2)


def _load_state():
    if not os.path.exists(STATE_FILE):
        sys.exit("No previous search found — run `find_award.py search ...` first.")
    with open(STATE_FILE) as f:
        return json.load(f)


# ---------- favorites store ----------
def _fav_dir(fid):
    return os.path.join(FAVORITES_DIR, fid)


def save_favorite(page, row, origin, dest, cabin):
    """Persist a flight: flight.json + screenshot.png + page.html (the 'experience')."""
    fid = row.get("fid") or row_fid(row)
    d = _fav_dir(fid)
    os.makedirs(d, exist_ok=True)
    link = row.get("DeepLink")
    if page is not None and link:
        try:
            from browser.session import goto, human_pause
            goto(page, link)
            human_pause(1.0, 2.0)
            page.screenshot(path=os.path.join(d, "screenshot.png"), full_page=True)
            with open(os.path.join(d, "page.html"), "w") as f:
                f.write(page.content())
        except Exception as e:
            print(f"[favorite {fid}] snapshot failed: {e}", file=sys.stderr)
    record = {"fid": fid, "origin": origin, "dest": dest, "cabin": cabin,
              "checked_at": dt.datetime.now().isoformat(timespec="seconds"),
              "flight": row, "history": [{"checked_at": dt.datetime.now().isoformat(timespec="seconds"),
                                          "miles": row.get("miles"), "taxes": row.get("taxes")}]}
    with open(os.path.join(d, "flight.json"), "w") as f:
        json.dump(record, f, indent=2)
    return fid


def load_favorites():
    if not os.path.isdir(FAVORITES_DIR):
        return []
    favs = []
    for name in sorted(os.listdir(FAVORITES_DIR)):
        fp = os.path.join(FAVORITES_DIR, name, "flight.json")
        if os.path.exists(fp):
            with open(fp) as f:
                favs.append(json.load(f))
    return favs


def refresh_favorite(page, fav):
    """Reopen the favorite's flight in real Chrome, re-scrape its route/date,
    match the flight number, update miles + delta + snapshot."""
    from browser import airlines as airpkg
    from browser.session import goto, human_pause

    flight = fav["flight"]
    prev_miles = flight.get("miles")
    name = flight.get("program", "")
    fid = fav["fid"]
    try:
        date = parse_date(flight["date"])
        q = Query([flight.get("OriginAirport")], airports.expand(fav["dest"]),
                  date, date, fav.get("cabin", "economy"), set(), 0, None, None)
        mod = airpkg.get(name)
        rows = mod.scrape(page, q) or []
        match = next((r for r in rows
                      if str(r.get("FlightNumbers")) == str(flight.get("FlightNumbers"))), None)
        if match is None and rows:
            match = rank(rows, fav.get("cabin", "economy"), set(), 0)[:1]
            match = match[0] if match else None
    except Exception as e:
        print(f"[refresh {fid}] scrape failed: {e}", file=sys.stderr)
        match = None

    new = rank([match], fav.get("cabin", "economy"), set(), 0)[0] if match else None
    cur_miles = new["miles"] if new else None
    delta = (cur_miles - prev_miles) if (cur_miles is not None and prev_miles is not None) else None

    if new:
        new["fid"] = fid
        fav["flight"] = new
    fav["checked_at"] = dt.datetime.now().isoformat(timespec="seconds")
    fav.setdefault("history", []).append(
        {"checked_at": fav["checked_at"], "miles": cur_miles, "taxes": new.get("taxes") if new else None})

    # persist + fresh snapshot
    d = _fav_dir(fid)
    link = (new or flight).get("DeepLink")
    if link:
        try:
            goto(page, link)
            human_pause(1.0, 2.0)
            page.screenshot(path=os.path.join(d, "screenshot.png"), full_page=True)
            with open(os.path.join(d, "page.html"), "w") as f:
                f.write(page.content())
        except Exception as e:
            print(f"[refresh {fid}] snapshot failed: {e}", file=sys.stderr)
    with open(os.path.join(d, "flight.json"), "w") as f:
        json.dump(fav, f, indent=2)
    return {"fid": fid, "miles": cur_miles, "delta": delta}


# ---------- subcommands ----------
def cmd_search(args):
    rows = run_search(
        origin=args.__dict__["from"], dest=args.to,
        start=parse_date(args.start), end=parse_date(args.end),
        cabin=args.cabin, airlines=[a.strip() for a in args.airlines.split(",") if a.strip()],
        weekdays=args.weekdays, max_miles=args.max_miles,
        after=args.depart_after, before=args.depart_before, headless=args.headless)

    origin, dest = args.__dict__["from"], args.to
    if not rows:
        print("No award space found for those parameters.", file=sys.stderr)
    print(build_table(rows, origin, dest))
    _save_state(rows, origin, dest, args.cabin)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    out = os.path.join(REPORTS_DIR, f"{origin}-{dest}-{args.start}_{args.end}.md")
    write_report(out, origin, dest, rows, start=args.start, end=args.end, cabin=args.cabin,
                 weekdays=args.weekdays, sources=args.airlines, max_miles=args.max_miles,
                 source_label="Live airline scrape")
    print(f"\nReport written to {out}", file=sys.stderr)


def cmd_favorite(args):
    from browser import session
    state = _load_state()
    rows = state["rows"]
    if args.id:
        chosen = [r for r in rows if (r.get("fid") or row_fid(r)) == args.id]
    else:
        chosen = rows[:args.last]
    if not chosen:
        sys.exit("Nothing matched to favorite.")
    with session.open_context() as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for r in chosen:
            fid = save_favorite(page, r, state["origin"], state["dest"], state["cabin"])
            print(f"Favorited {fid}  ({r['miles']:,} mi)", file=sys.stderr)


def cmd_list(args):
    favs = load_favorites()
    if not favs:
        print("No favorites yet.")
        return
    print(f"{'FID':<48} {'MILES':>8}  {'TAXES':>7}  CHECKED")
    for fav in favs:
        fl = fav["flight"]
        taxes = fl.get("taxes")
        print(f"{fav['fid']:<48} {fl.get('miles', '?'):>8}  "
              f"{('$'+str(taxes)) if taxes is not None else '?':>7}  {fav.get('checked_at', '?')}")


def cmd_refresh(args):
    from browser import session
    favs = load_favorites()
    targets = favs if args.all else [f for f in favs if f["fid"] == args.id]
    if not targets:
        sys.exit("No matching favorites to refresh (use --all or --id <fid>).")
    with session.open_context() as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for fav in targets:
            res = refresh_favorite(page, fav)
            d = res["delta"]
            tag = "no change" if d == 0 else (f"{d:+,}" if d is not None else "n/a")
            print(f"{res['fid']}: {res['miles']} mi ({tag})")


_LOGIN_SITES = {
    "United": "https://www.united.com/en/us/account/login",
    "Delta": "https://www.delta.com/login/home",
    "American": "https://www.aa.com",
    "JetBlue": "https://www.jetblue.com",
}


def cmd_login(args):
    """Open a headed browser on the tool's profile so you can sign in once; the
    sessions persist for later searches/reloads. Run this in your own Terminal."""
    from browser import session
    print("Opening a browser for sign-in. Log into each airline in the tabs that open,\n"
          "then come back here and press Enter to save the session and close.", file=sys.stderr)
    with session.open_context(headless=False) as ctx:
        first = True
        for name, url in _LOGIN_SITES.items():
            page = (ctx.pages[0] if (first and ctx.pages) else ctx.new_page())
            first = False
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"[login] {name}: {e}", file=sys.stderr)
        try:
            input("\nPress Enter when you've finished logging in… ")
        except EOFError:
            print("No interactive stdin; keeping browser open 180s instead.", file=sys.stderr)
            import time
            time.sleep(180)
    print("Session saved to your award-travel Chrome profile.", file=sys.stderr)


def cmd_serve(args):
    try:
        import uvicorn  # noqa: F401
        from web.server import app  # noqa: F401
    except Exception:
        sys.exit("Web app not yet built (Phase 3). Install fastapi+uvicorn and add web/server.py.")
    import uvicorn
    uvicorn.run("web.server:app", host="127.0.0.1", port=args.port, reload=False)


def build_parser():
    p = argparse.ArgumentParser(description="Live award-flight tool (real Chrome).")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="search award space across airlines over a day range")
    s.add_argument("--from", required=True, help="Origin metro/airport, e.g. NYC or JFK")
    s.add_argument("--to", required=True, help="Destination metro/airport, e.g. PHX")
    s.add_argument("--start", required=True, help="Day range start YYYY-MM-DD")
    s.add_argument("--end", required=True, help="Day range end YYYY-MM-DD")
    s.add_argument("--weekdays", default="", help="Optional filter, e.g. Wed,Thu")
    s.add_argument("--cabin", default="economy", choices=["economy", "premium", "business", "first"])
    s.add_argument("--max-miles", type=int, default=0, dest="max_miles")
    s.add_argument("--airlines", default=",".join(DEFAULT_AIRLINES))
    s.add_argument("--depart-after", default=None, dest="depart_after", help="HH:MM")
    s.add_argument("--depart-before", default=None, dest="depart_before", help="HH:MM")
    s.add_argument("--headless", action="store_true")
    s.set_defaults(func=cmd_search)

    f = sub.add_parser("favorite", help="save a flight from the last search")
    g = f.add_mutually_exclusive_group()
    g.add_argument("--id", help="favorite the result with this fid")
    g.add_argument("--last", type=int, default=1, help="favorite the top N results (default 1)")
    f.set_defaults(func=cmd_favorite)

    sub.add_parser("list", help="list saved favorites").set_defaults(func=cmd_list)

    sub.add_parser("login", help="sign into airlines once (persists for United/Delta)").set_defaults(func=cmd_login)

    r = sub.add_parser("refresh", help="reopen favorite(s) and re-verify miles")
    rg = r.add_mutually_exclusive_group(required=True)
    rg.add_argument("--id", help="refresh one favorite by fid")
    rg.add_argument("--all", action="store_true", help="refresh all favorites")
    r.set_defaults(func=cmd_refresh)

    sv = sub.add_parser("serve", help="launch the local web app")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(func=cmd_serve)
    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
