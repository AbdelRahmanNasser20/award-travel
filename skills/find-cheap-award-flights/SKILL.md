---
name: find-cheap-award-flights
description: Find the cheapest points/miles (award) flights between two airports over a date range, across United, American, Delta, Southwest, JetBlue, Frontier and their transfer partners. Use whenever the user wants to "find cheap flights with points/miles", "award availability", "book with points", or names a route + dates and a miles budget. Outputs a ranked list in chat plus a saved report file with booking links.
---

# Find Cheap Award Flights

Find the lowest points/miles cost to fly a route over a date range, then hand back a
ranked list and a saved report with booking links. Two methods are supported; run the
API method when a key is available, otherwise the browser method.

## What the user must provide (ask if missing)
- **Origin + destination** (airport or metro codes). Metro NYC = `JFK,LGA,EWR`. Phoenix = `PHX`.
- **Date range** (start + end, YYYY-MM-DD). A weekday pattern like "any Wed–Thu in June" → expand to every Wed/Thu in that month.
- **Cabin** (economy / premium / business / first). Default economy.
- **Miles budget** (e.g. 9,000–17,000 each way). Used to filter + flag good deals.
- **Passengers** and **one-way vs round-trip** (award trips are priced as two one-ways — search each direction separately).

## Default trip for this project
NYC → Phoenix, economy, every Wednesday and Thursday in the target month, 9k–17k miles
each way, 1 passenger. Confirm the month/year before searching (dates change yearly).

---

## CREDENTIALS — read this first
**Never write the user's airline passwords into a file or into memory.** They are secrets.
The skill does NOT need stored passwords:
- **API method** needs only a Seats.aero **API key** (not an airline password). Store the
  key in an env var `SEATS_AERO_API_KEY`, never hard-coded in a file.
- **Browser method** uses the user's **already-logged-in browser session**. Drive
  *their* browser; let them log in themselves (or rely on saved logins in their browser /
  password manager). Do not type passwords from a stored file.

If the user pasted passwords in chat, do not persist them. Recommend a password manager and
unique passwords per site (reusing one password across all airline accounts is a real risk).

---

## METHOD A — Seats.aero API (preferred: fast, structured, all programs at once)

Requires a Seats.aero **Pro** membership (~$9.99/mo) and an API key. Aggregates live award
availability across major programs — this is the engine Roame-style tools are built on.

Run the helper script (it handles paging, filtering, ranking, and report writing):

```bash
export SEATS_AERO_API_KEY="<the user's key>"
python3 scripts/search_seats_aero.py \
  --origin JFK,LGA,EWR \
  --destination PHX \
  --start 2026-06-03 --end 2026-06-25 \
  --weekdays Wed,Thu \
  --cabin economy \
  --sources united,delta,american,jetblue,southwest,frontier \
  --max-miles 17000 \
  --out "../report.md"
```

Endpoint reference (in case you need to call it directly):
- `GET https://seats.aero/partnerapi/search`
- Header: `Partner-Authorization: <API key>`
- Key params: `origin_airport`, `destination_airport`, `start_date`, `end_date` (YYYY-MM-DD),
  `cabin` (economy|premium|business|first), `sources` (comma list of programs),
  `order_by=lowest_mileage`, `only_direct_flights=true|false`, `take` (10–1000), `cursor`.
- Response per result includes `Source` (program), `YMileageCost`/`WMileageCost`/`JMileageCost`/`FMileageCost`
  (economy/premium/business/first), `TotalTaxes`, `Date`, and route info.

Program names for `sources`: `united`, `delta`, `american`, `aeroplan` (United partner via
Chase), `jetblue`, `southwest`, `flyingblue`, `velocity`, etc. Map to the user's balances.

## METHOD B — Live real-Chrome tool (`find_award.py`, real-time, no subscription)

The repo ships an automated browser tool that drives the user's **real, already-logged-in
Chrome profile** (Playwright, `channel="chrome"`) to read live miles prices off each airline
site. This is the real-time path (the cached seats.aero API can be hours–days stale). Setup:

```bash
pip install -r requirements.txt && playwright install chrome
cp scripts/.env.example scripts/.env      # set AWARD_CHROME_PROFILE (+ optional GROQ_API_KEY)
```

CLI (run from `scripts/`):

```bash
python find_award.py search --from NYC --to PHX --start 2026-07-13 --end 2026-07-19 \
  --weekdays Wed,Thu --cabin economy --max-miles 17000 \
  --airlines united,american,jetblue,southwest,frontier,delta
python find_award.py favorite --last 1     # save flight (data + screenshot + page HTML)
python find_award.py list                  # saved favorites + last-checked miles
python find_award.py refresh --all         # reopen favorites, re-verify current miles + delta
python find_award.py serve                 # roame-style web app at http://localhost:8000
```

How it works:
- **Metro expansion** (`browser/airports.py`): NYC→JFK/LGA/EWR, DC→DCA/IAD/BWI, etc.
  United/American/Delta/JetBlue search the metro together; **Southwest/Frontier** are searched
  one airport at a time and de-duped (`SUPPORTS_METRO=False`).
- **Per-airline scrapers** (`browser/airlines/*.py`) all return the raw Seats.aero row shape, so
  results flow through the shared `award_common.rank`/`build_table`/`write_report` engine.
- **Human-like pacing** (`browser/session.py`) and the user's real logged-in session (no stored
  passwords).
- **Groq LLM extraction fallback** (`browser/llm_extract.py`): if a scraper's selectors break,
  and `GROQ_API_KEY` is set, the page HTML is trimmed + PII-scrubbed and a free Groq model
  re-extracts the rows; it logs "LLM fallback fired — update selectors". Skipped if no key.
- **Web app** (`web/`): roame-style search bar (From/To metro chips, day range, cabin, Live vs
  cached SkyView toggle), result cards with ★-favorite, and a Favorites page with per-card +
  Reload-all that streams live miles + delta over SSE. One real-Chrome browser, jobs queued.

> Scraper selectors are best-effort and marked `# VERIFY`; expect a one-time tuning pass on the
> first real run (the Groq fallback is the backstop). Airline anti-bot (United/Delta) may still
> require an occasional manual login even on a real profile.

### Manual fallback — Claude-in-Chrome
If the automated tool isn't available, drive the user's browser by hand through each airline's
award search. Toggle "Shop with miles / Award travel" ON, search **one direction at a time**,
scan the calendar/low-fare view for the cheapest day, record miles + taxes.

Award search entry points:
- United — https://www.united.com (set "Book with miles" before searching)
- American — https://www.aa.com (check "Redeem miles")
- Delta — https://www.delta.com (toggle "Shop with Miles")
- Southwest — https://www.southwest.com (select "Points")
- JetBlue — https://www.jetblue.com (TrueBlue points toggle)
- Frontier — https://www.flyfrontier.com (Frontier Miles)

For each airline, capture: date, flight number, departure/arrival times, stops, **miles**,
**cash taxes/fees**, and the page URL. Skip results above the miles budget unless nothing
cheaper exists (then flag them).

### Airline-specific browser notes (learned from real runs)
- **United** requires sign-in to view miles pricing ("You must be signed-in to see flight
  results with miles"). Have the user log in (never type their password). Then use the
  "30-day calendar" link on the results page to read cheapest miles per day at once. United
  auto-expands to all NYC airports when origin = New York.
- **American** shows AAdvantage award without login. Use the advanced search form at
  aa.com (check "Redeem miles"), origin "NYC - New York, NY" for all airports. The date
  strip + Main/Business/First columns give per-day, per-cabin miles. Often has nonstops.
- **JetBlue & Southwest** show points without login via the date deep links above — fastest.
- **Delta** shows SkyMiles without login but the homepage **constantly polls the network, so
  screenshot/read tools time out waiting for document_idle**. Workarounds that worked:
  1. Build the search using element refs from the `find` tool, not pixel coordinates (the
     layout reflows and coordinates drift).
  2. Set trip type, origin (NYC), destination (PHX), then the date. With "My Dates are
     Flexible" on, you must actually select a day in the calendar (a stray "Done" with no
     day selected clears it and triggers "Date is Required").
  3. Click "Find Flights" — this navigates to `/flightsearch/flexible-dates`, a results page
     that DOES settle and is readable. The flexible-dates strip shows lowest miles for ~7
     days around your date. Toggle "Show Price In: Miles" and "Non Stop / All Flights".
  Delta domestic economy is dynamically priced and usually far above a 9–17k budget
  (NYC→PHX was 22,600+ one-way), so it rarely wins on cheap domestic routes.

## Comparing the two methods
When both are run, present them side by side per route/date: API result vs. what the airline
site shows. They can differ (cache lag, partner-only space, dynamic pricing). Trust the
**airline site** for the final bookable number; use the API for fast discovery.

---

## Output format (always produce BOTH)

1. **Ranked list in chat** — cheapest miles first. One row per option:

   | Date | Airline/Program | Route | Stops | Depart→Arrive | Miles | + Taxes | Deal? | Book |
   |------|-----------------|-------|-------|---------------|-------|---------|-------|------|

   - "Deal?" = ✅ if at/below the user's miles budget, ⚠️ if slightly over, ❌ well over.
   - "Book" = a clickable link (airline award page or Seats.aero result URL).

2. **Saved report file** — write a markdown report to the project folder (`report.md` by
   default, or a dated name like `nyc-phx-2026-06.md`). Include the same table, the search
   parameters used, the timestamp, and a short "best pick" recommendation. Present the file
   with the present_files tool so the user can open it.

## Booking links
- Seats.aero result pages: link straight from the API response when available.
- Airline deep links are unstable; if a precise deep link isn't reliable, link to the
  airline's award search page and state the exact date + flight number to enter.
- Always include a cash-fare comparison (Google Flights:
  `https://www.google.com/travel/flights?q=Flights%20JFK%20to%20PHX%20on%20YYYY-MM-DD`) so
  the user can judge cents-per-point value.

## Good-deal heuristics (domestic economy)
- ~9k–17k miles one-way NYC↔PHX is a fair-to-good domestic economy redemption.
- Watch cash fees: some "cheap miles" results carry higher taxes; rank by miles **and** flag fees.
- Saver/partner space disappears fast — tell the user to book promptly when a ✅ appears.

## Steps to run the skill
1. Confirm route, dates (expand weekday patterns), cabin, miles budget, passengers, direction.
2. If `SEATS_AERO_API_KEY` is set → run Method A. Else (or to compare) → Method B.
3. Filter by budget, rank by miles (then taxes).
4. Print the ranked table in chat AND write the report file.
5. Present the report file. Recommend the single best pick and note availability is volatile.
