# Planning Context — award-travel (roame.travel clone)

This doc captures decisions from the brainstorming session so a fresh (remote/cloud)
planning session has full context. The local award-flights skill is NOT in this repo, so
its mechanics are summarized below.

## Goal
Build a **roame.travel-style** flight search app: search **cash fares** via flight APIs and
find **award (points/miles) availability** by integrating the `find-cheap-award-flights`
skill (Seats.aero Partner API logic).

## Decisions (from brainstorming)
- **Scope:** Search + **user accounts** + **availability alerts**. (Not the full clone: no
  points-valuation engine / deal feed in v1.)
- **Stack:** **Next.js** full-stack (TypeScript + Tailwind, API routes for backend).
- **Data sources:**
  - **Cash fares first** — use a cash-fare flight API (e.g. Amadeus / Duffel / Kiwi; free
    tiers available). This is the primary v1 data path.
  - **Award availability** — integrate the `find-cheap-award-flights` skill, which uses the
    **Seats.aero Partner API**. Open design question: port the skill's Python logic to a
    TypeScript API route (cleaner for a web app) vs. shelling out to the Python script.

## The `find-cheap-award-flights` skill (summary; source lives locally, not in repo)
Two methods:
- **Method A (preferred): Seats.aero Partner API**
  - `GET https://seats.aero/partnerapi/search`
  - Header: `Partner-Authorization: <SEATS_AERO_API_KEY>` (Seats.aero Pro key, ~$10/mo — NOT
    an airline password; never store airline passwords).
  - Params: `origin_airport`, `destination_airport`, `start_date`, `end_date` (YYYY-MM-DD),
    `cabin` (economy|premium|business|first), `sources` (comma list: united, delta, american,
    aeroplan, jetblue, southwest, flyingblue, velocity…), `order_by=lowest_mileage`,
    `only_direct_flights=true|false`, `take` (10–1000), `cursor` (paging).
  - Response per result: `Source` (program), `YMileageCost`/`WMileageCost`/`JMileageCost`/
    `FMileageCost` (econ/prem/biz/first), `TotalTaxes`, `Date`, route info, `ID`.
  - Logic: page via cursor → filter by weekday/budget → rank by miles then taxes → flag deals
    (✅ ≤ budget, ⚠️ ≤ budget×1.15, ❌ over) → output ranked table + markdown report.
- **Method B (fallback): browser automation** across United/AA/Delta/Southwest/JetBlue/
  Frontier award pages (toggle "shop with miles"). Slower/fragile; not relevant to a web app
  backend except as inspiration.

## Suggested v1 feature set
1. Search page: origin/destination (incl. metro codes like JFK,LGA,EWR), date or date range,
   cabin, passengers, one-way/round-trip.
2. Results: cash fares ranked by price; award results ranked by miles + taxes, deal flags,
   booking links. Cash-vs-points comparison (cents-per-point context).
3. Accounts: sign up / log in, save searches.
4. Alerts: notify when award space or a fare appears at/under a target for a saved search.

## Security notes
- Never store airline passwords. Seats.aero key in env var `SEATS_AERO_API_KEY`.
- Keep all third-party API keys server-side (API routes), never shipped to the client.
