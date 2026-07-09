#!/usr/bin/env python3
"""On-demand HEB session refresh — launches YOUR real Chrome, captures silently.

The tool's own ``session_refresh`` launches a Playwright browser that HEB's
Imperva WAF hard-blocks. This instead drives your *real* Chrome against a
dedicated, persistent profile so the WAF sees a genuine browser. Flow:

1. If no debugged Chrome is already up, launch the real Chrome binary with a
   remote-debugging port against ``~/.heb-chrome-profile`` (a profile separate
   from your everyday one).
2. Attach over CDP, open heb.com, and watch for a *fresh* reese84 token.
   - If the session is still warm (used recently), reese84 renews on its own
     and we capture ``auth.json`` + persisted-query hashes with zero clicks.
   - If it has fully lapsed (or you've never logged in on this profile), reese84
     can't be regained silently — HEB requires re-passing Imperva's human
     challenge. We bring the window forward and tell you to sign in ONCE; rerun
     and it's warm from then on.

We deliberately do NOT simulate human input to defeat the challenge — the
one-time interactive login is a security boundary, not a bug.

Chrome is left running after a successful refresh so the session stays warm for
the rest of your work session; pass --close to quit it, or run
``pkill -f heb-chrome-profile``.

Exit codes: 0 = refreshed (warm, captured); 2 = login needed (window is open).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import time
import urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE = os.path.expanduser("~/.heb-chrome-profile")
AUTH = os.path.expanduser("~/.texas-grocery-mcp/auth.json")
CACHE = os.path.expanduser("~/.texas-grocery-mcp/persisted_query_cache.json")
PORT = 9222

KNOWN_OPS = {
    "ShopNavigation", "alertEntryPoint", "cartEstimated", "typeaheadContent",
    "cartItemV2", "StoreSearch", "CouponClip", "SelectPickupFulfillment",
    "listPickupTimeslotsV2", "ReserveTimeslot", "getShoppingListsV2",
    "getShoppingListV2", "addToShoppingListV2", "deleteShoppingListItems",
}

# In-page JS to dump localStorage as [{name, value}] (reese84 lives here).
_LS_JS = "() => Object.keys(localStorage).map(k => ({name:k, value:localStorage.getItem(k)}))"


def _port_up() -> bool:
    try:
        urllib.request.urlopen(f"http://localhost:{PORT}/json/version", timeout=2)
        return True
    except Exception:
        return False


def _launch_chrome() -> None:
    os.makedirs(PROFILE, exist_ok=True)
    subprocess.Popen(
        [CHROME, f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
         "--no-first-run", "--no-default-browser-check", "https://www.heb.com/"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(25):
        if _port_up():
            return
        time.sleep(1)


def _reese_fresh(items: list[dict]) -> bool:
    for it in items:
        if it["name"] == "reese84":
            try:
                return json.loads(it["value"]).get("renewTime", 0) / 1000 > time.time()
            except Exception:
                return False
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wait", type=int, default=25, help="seconds to wait for a warm token")
    ap.add_argument("--close", action="store_true", help="quit Chrome after capture")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    launched = False
    if not _port_up():
        _launch_chrome()
        launched = True
    if not _port_up():
        print("ERROR: could not start Chrome with the debug port.")
        return 2

    found: dict[str, str] = {}

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{PORT}")
        ctx = browser.contexts[0]

        def harvest(req):
            try:
                if "graphql" not in req.url.lower() or req.method != "POST" or not req.post_data:
                    return
                body = req.post_data
                docs = json.loads(body) if body.lstrip().startswith("[") else [json.loads(body)]
                for d in docs:
                    op = d.get("operationName")
                    h = (d.get("extensions") or {}).get("persistedQuery", {}).get("sha256Hash")
                    if op in KNOWN_OPS and h:
                        found.setdefault(op, h)
            except Exception:
                pass

        ctx.on("request", harvest)
        page = next((x for x in ctx.pages if "heb.com" in x.url), None) or ctx.new_page()
        with contextlib.suppress(Exception):
            page.goto("https://www.heb.com/", wait_until="domcontentloaded", timeout=45000)

        # Poll for a warm token.
        warm = False
        deadline = time.time() + args.wait
        while time.time() < deadline:
            items = page.evaluate(_LS_JS)
            if _reese_fresh(items):
                warm = True
                break
            time.sleep(3)

        if not warm:
            # Cold — needs the one-time human login. Bring the window forward.
            with contextlib.suppress(Exception):
                page.bring_to_front()
                subprocess.run(
                    ["osascript", "-e", 'tell application "Google Chrome" to activate'],
                    capture_output=True,
                )
            print("LOGIN NEEDED: a Chrome window is open at heb.com on the .heb-chrome-profile.")
            print("Sign in (clear any 'verify you are human' check) once, then rerun this script.")
            return 2

        # Warm: load the cart page too so mutation hashes get captured, then save.
        with contextlib.suppress(Exception):
            page.goto("https://www.heb.com/cart", wait_until="domcontentloaded", timeout=45000)
        time.sleep(4)

        cookies = ctx.cookies()
        origins, reese = [], None
        for pg in ctx.pages:
            if "heb.com" not in pg.url:
                continue
            ls = pg.evaluate(_LS_JS)
            entry = {"origin": pg.evaluate("() => location.origin"), "localStorage": ls}
            if any(i["name"] == "reese84" for i in ls):
                reese = entry
            else:
                origins.append(entry)
        if reese:
            origins.insert(0, reese)
        os.makedirs(os.path.dirname(AUTH), exist_ok=True)
        with open(AUTH, "w") as f:
            json.dump({"cookies": cookies, "origins": origins}, f, indent=1)

        if found:
            cache = {"hashes": {}, "last_discovery": 0.0}
            if os.path.exists(CACHE):
                with contextlib.suppress(Exception), open(CACHE) as f:
                    cache = json.load(f)
            cache.setdefault("hashes", {}).update(found)
            cache["last_discovery"] = time.time()
            with open(CACHE, "w") as f:
                json.dump(cache, f, indent=1)

        if args.close:
            subprocess.run(["pkill", "-f", "heb-chrome-profile"], capture_output=True)

    print(f"OK: session refreshed{' (launched Chrome)' if launched else ''}. "
          f"Captured hashes: {sorted(found) or 'none new'}. auth.json updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
