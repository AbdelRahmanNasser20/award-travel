#!/bin/bash
# Double-click this file in Finder to sign into the airlines for the award tool.
# It opens a Chrome window (United/Delta/American/JetBlue). Log in, then return here
# and press Enter — your session is saved to the tool's profile and reused by searches
# and the web app. No passwords are stored.
cd "$(dirname "$0")" || exit 1

PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "First-time setup: creating the Python environment…"
  python3 -m venv .venv && .venv/bin/pip install -q -r ../requirements.txt && .venv/bin/playwright install chrome
fi

echo "Opening the sign-in browser…"
"$PY" find_award.py login
echo
echo "Done. You can close this window."
