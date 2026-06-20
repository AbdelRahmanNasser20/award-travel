#!/usr/bin/env python3
"""
Groq LLM extraction fallback (extraction ONLY).

Deterministic selectors always run first. When a scraper returns nothing (its
`signature(page)` is false / the site's HTML changed), the runner calls
`extract_from_page(page, query, airline)`: we trim the page to the results region,
scrub PII, and ask a free Groq model to return the flight rows as JSON in the same
raw shape the ranker expects.

Disabled entirely when GROQ_API_KEY is unset — the tool still works, the broken
scraper just reports failure. Every fallback fires a loud log line so the real
selectors get fixed.
"""
import json
import os
import re
import sys

CABIN_FIELD = {
    "economy": "YMileageCost", "premium": "WMileageCost",
    "business": "JMileageCost", "first": "FMileageCost",
}
_MAX_CHARS = 18000  # keep well under model context; we only need the results region


def enabled() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def _trim_html(html: str) -> str:
    """Drop scripts/styles/svg/head noise and keep a results-sized slice."""
    for tag in ("script", "style", "svg", "noscript", "head", "header", "footer"):
        html = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    html = re.sub(r"\s+", " ", html)
    # Prefer a slice around the first miles/points mention (the results region).
    m = re.search(r"(miles|points|award)", html, flags=re.I)
    if m:
        start = max(0, m.start() - 1500)
        return html[start:start + _MAX_CHARS]
    return html[:_MAX_CHARS]


def _scrub_pii(text: str) -> str:
    """Remove obvious account PII before sending to a third party."""
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email]", text)           # emails
    text = re.sub(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b", "[phone]", text)  # phones
    text = re.sub(r"\b[A-Z0-9]{7,}\b", "[id]", text)                      # loyalty/conf ids
    return text


def _coerce_rows(data, query, airline):
    rows = data.get("rows", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    field = CABIN_FIELD.get(query.cabin, "YMileageCost")
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        miles = r.get(field) or r.get("miles") or r.get("MileageCost")
        try:
            miles = int(str(miles).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if miles <= 0 or not r.get("Date"):
            continue
        out.append({
            "Source": airline,
            field: miles,
            "TotalTaxes": r.get("TotalTaxes") or r.get("taxes"),
            "Date": str(r["Date"])[:10],
            "Direct": bool(r.get("Direct")),
            "OriginAirport": r.get("OriginAirport"),
            "DestinationAirport": r.get("DestinationAirport"),
            "FlightNumbers": r.get("FlightNumbers"),
            "DepartTime": r.get("DepartTime"),
            "ArriveTime": r.get("ArriveTime"),
            "DeepLink": r.get("DeepLink"),
        })
    return out


def extract_with_llm(html_section, query, airline) -> list:
    """Core: hand cleaned HTML to Groq, return validated raw-shape rows."""
    if not enabled():
        return []
    try:
        from groq import Groq
    except Exception:
        print("[llm_extract] groq package not installed; skipping fallback", file=sys.stderr)
        return []

    cleaned = _scrub_pii(_trim_html(html_section or ""))
    if not cleaned.strip():
        return []
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    field = CABIN_FIELD.get(query.cabin, "YMileageCost")
    prompt = (
        f"Extract award flights for {airline} from this HTML fragment. Cabin: {query.cabin}.\n"
        f"Return STRICT JSON: {{\"rows\": [{{ \"{field}\": <int miles>, \"TotalTaxes\": <number>, "
        '"Date": "YYYY-MM-DD", "Direct": <bool>, "OriginAirport": "XXX", '
        '"DestinationAirport": "XXX", "FlightNumbers": "AA123", "DepartTime": "HH:MM", '
        '"ArriveTime": "HH:MM" }}]}. Only include rows with a real miles/points price. '
        f"If none are present, return {{\"rows\": []}}.\n\nHTML:\n{cleaned}"
    )
    try:
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        data = json.loads(resp.choices[0].message.content)
    except Exception as e:
        print(f"[llm_extract] Groq call failed for {airline}: {e}", file=sys.stderr)
        return []
    return _coerce_rows(data, query, airline)


def extract_from_page(page, query, airline) -> list:
    """Convenience wrapper used by the runner: read the page HTML and extract."""
    if not enabled():
        return []
    print(f"LLM fallback fired for {airline} — update selectors", file=sys.stderr)
    try:
        html = page.content()
    except Exception as e:
        print(f"[llm_extract] could not read page for {airline}: {e}", file=sys.stderr)
        return []
    return extract_with_llm(html, query, airline)
