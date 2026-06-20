#!/usr/bin/env python3
"""
FastAPI backend for the roame-style award web app.

Reuses the Phase 1 search + favorites + refresh logic directly. The real Chrome
profile can't be opened twice, so a single global lock serializes every browser
job (search / favorite / reload); Playwright's sync API runs in worker threads so
it never blocks the event loop. Reload progress streams to the UI over SSE.

Launch with:  python find_award.py serve     (or: uvicorn web.server:app)
"""
import asyncio
import json
import os
import sys
import threading

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# find_award lives one dir up on sys.path when launched via `find_award.py serve`;
# add the scripts dir defensively so `uvicorn web.server:app` also works.
SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import find_award as fa  # noqa: E402
from browser import airports  # noqa: E402

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(title="Award Flights")
_browser_lock = threading.Lock()   # one real-Chrome job at a time


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/search")
async def api_search(request: Request):
    p = request.query_params
    mode = p.get("mode", "live")
    try:
        if mode == "cached":
            rows = await asyncio.to_thread(_cached_search, p)
        else:
            rows = await asyncio.to_thread(_live_search, p)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return {"rows": rows, "mode": mode}


def _live_search(p):
    with _browser_lock:
        rows = fa.run_search(
            origin=p["from"], dest=p["to"],
            start=fa.parse_date(p["start"]), end=fa.parse_date(p["end"]),
            cabin=p.get("cabin", "economy"),
            airlines=[a for a in p.get("airlines", ",".join(fa.DEFAULT_AIRLINES)).split(",") if a],
            weekdays=p.get("weekdays", ""), max_miles=int(p.get("max_miles", 0) or 0),
            after=p.get("depart_after") or None, before=p.get("depart_before") or None)
    fa._save_state(rows, p["from"], p["to"], p.get("cabin", "economy"))
    return rows


def _cached_search(p):
    """SkyView (seats.aero cached API) path — no browser needed."""
    import search_seats_aero as sa
    key = os.environ.get("SEATS_AERO_API_KEY")
    if not key:
        raise RuntimeError("SEATS_AERO_API_KEY not set (required for Cached/SkyView mode)")
    wd = fa.parse_weekdays(p.get("weekdays", ""))
    params = {
        "origin_airport": ",".join(airports.expand(p["from"])),
        "destination_airport": ",".join(airports.expand(p["to"])),
        "start_date": p["start"], "end_date": p["end"],
        "cabin": p.get("cabin", "economy"),
        "sources": p.get("airlines", ",".join(fa.DEFAULT_AIRLINES)),
        "order_by": "lowest_mileage", "take": 1000,
    }
    raw = sa.fetch(params, key)
    rows = fa.rank(raw, p.get("cabin", "economy"), wd, int(p.get("max_miles", 0) or 0))
    for r in rows:
        r["fid"] = fa.row_fid(r)
    fa._save_state(rows, p["from"], p["to"], p.get("cabin", "economy"))
    return rows


@app.get("/api/favorites")
def api_favorites():
    return {"favorites": fa.load_favorites()}


@app.post("/api/favorites")
async def api_add_favorite(request: Request):
    body = await request.json()
    row = body.get("row")
    if not row:
        return JSONResponse({"error": "row required"}, status_code=400)
    origin = body.get("origin", row.get("OriginAirport", ""))
    dest = body.get("dest", row.get("DestinationAirport", ""))
    cabin = body.get("cabin", "economy")
    fid = await asyncio.to_thread(_save_fav, row, origin, dest, cabin)
    return {"fid": fid}


def _save_fav(row, origin, dest, cabin):
    from browser import session
    with _browser_lock:
        with session.open_context() as ctx:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            return fa.save_favorite(page, row, origin, dest, cabin)


# ---- reload + SSE progress ----
_events: "asyncio.Queue" = None


@app.on_event("startup")
async def _startup():
    global _events
    _events = asyncio.Queue()


@app.post("/api/reload")
async def api_reload(request: Request):
    body = await request.json()
    ids = body.get("ids")  # list of fids, or None/"all" for everything
    loop = asyncio.get_running_loop()
    threading.Thread(target=_reload_worker, args=(ids, loop), daemon=True).start()
    return {"started": True}


def _emit(loop, event):
    if _events is not None:
        loop.call_soon_threadsafe(_events.put_nowait, event)


def _reload_worker(ids, loop):
    from browser import session
    favs = fa.load_favorites()
    if ids and ids != "all":
        favs = [f for f in favs if f["fid"] in set(ids)]
    try:
        with _browser_lock:
            with session.open_context() as ctx:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                for fav in favs:
                    _emit(loop, {"fid": fav["fid"], "status": "loading"})
                    try:
                        res = fa.refresh_favorite(page, fav)
                        _emit(loop, {"fid": res["fid"], "status": "done",
                                     "miles": res["miles"], "delta": res["delta"]})
                    except Exception as e:
                        _emit(loop, {"fid": fav["fid"], "status": "error", "error": str(e)})
    finally:
        _emit(loop, {"status": "complete"})


@app.get("/api/reload/stream")
async def api_reload_stream():
    async def gen():
        while True:
            event = await _events.get()
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("status") == "complete":
                break
    return StreamingResponse(gen(), media_type="text/event-stream")


# Static assets (after routes so they don't shadow /api).
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
