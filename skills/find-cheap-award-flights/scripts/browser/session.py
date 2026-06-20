#!/usr/bin/env python3
"""Real-Chrome Playwright session + human-like interaction helpers.

Drives your ACTUAL Chrome profile (already logged into the airlines) via a
persistent context. Only one context per process — the real profile can't be
opened twice — so the web server (Phase 3) owns a single context and queues work.
"""
import os
import random
import time as _time
from contextlib import contextmanager

DEFAULT_PROFILE = os.path.expanduser("~/.award-travel/chrome-profile")


def profile_dir(override=None) -> str:
    return override or os.environ.get("AWARD_CHROME_PROFILE") or DEFAULT_PROFILE


@contextmanager
def open_context(profile=None, headless=False):
    """Yield a persistent real-Chrome browser context. Imports Playwright lazily
    so the rest of the toolchain works without it installed."""
    from playwright.sync_api import sync_playwright

    path = profile_dir(profile)
    os.makedirs(path, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=path,
            channel="chrome",
            headless=headless,
            viewport={"width": 1440, "height": 1000},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            yield ctx
        finally:
            ctx.close()


def human_pause(lo=0.4, hi=1.2):
    _time.sleep(random.uniform(lo, hi))


def human_type(locator, text, lo=40, hi=160):
    """Type char-by-char with randomized per-key delay (ms)."""
    locator.click()
    human_pause(0.2, 0.5)
    for ch in str(text):
        locator.type(ch, delay=random.uniform(lo, hi))
    human_pause(0.2, 0.6)


def goto(page, url, timeout=60000):
    page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    human_pause(0.8, 1.8)
    return page
