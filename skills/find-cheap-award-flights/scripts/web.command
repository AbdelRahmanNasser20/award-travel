#!/bin/bash
# Double-click to launch the Award Flights web app and open it in your browser.
cd "$(dirname "$0")" || exit 1

PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "First-time setup: creating the Python environment…"
  python3 -m venv .venv && .venv/bin/pip install -q -r ../requirements.txt && .venv/bin/playwright install chrome
fi

( sleep 2 && open "http://127.0.0.1:8000/" ) &
echo "Starting the web app at http://127.0.0.1:8000  (press Ctrl+C in this window to stop)"
"$PY" find_award.py serve --port 8000
