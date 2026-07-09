#!/usr/bin/env python3
"""Refresh HEB's GraphQL persisted-query hashes from a live browser session.

HEB pins its GraphQL operations behind Automatic Persisted Query (APQ) hashes
and rotates them on deploy. When a hash goes stale the API rejects the request
with ``PersistedQueryNotFound`` and the affected tool (cart read/write, store
change, coupon clip) stops working. This script harvests the *current* hashes
straight from HEB's own frontend traffic so ``PERSISTED_QUERIES`` in
``clients/graphql.py`` can be updated.

Why a real browser: HEB fronts the site with an Imperva WAF that blocks a
fresh automated browser. Driving a normal Chrome you logged into yourself
sidesteps that — this script only *attaches* to it over the DevTools protocol
and reads the operation/hash pairs off the network.

Usage
-----
1. Launch Chrome with remote debugging on an isolated profile::

       "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
         --remote-debugging-port=9222 \\
         --user-data-dir="$HOME/.heb-chrome-profile"

   (Linux: ``google-chrome``; Windows: ``chrome.exe`` — same flags.)

2. In that window, sign in at https://www.heb.com and select a store.
3. Run this script::

       python scripts/refresh_persisted_hashes.py

It navigates a few read-only pages, then nudges a cart item's quantity by
+1/-1 (net-zero) to trigger the ``cartItemV2`` mutation, and prints a ready-to
-paste ``PERSISTED_QUERIES`` block plus a diff against the current constants.

Operations that only fire on account-mutating actions (``SelectPickupFulfillment``
on a store change, ``CouponClip`` on a clip) are captured only if you perform
those actions in the browser while the script is attached — it will not mutate
your account for you.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import time

try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover - dev convenience
    raise SystemExit(
        "playwright is required: pip install -e '.[browser]' && playwright install chromium"
    ) from exc

# Kept in sync with clients/graphql.py so we can print a diff.
CURRENT: dict[str, str] = {
    "ShopNavigation": "53197129989f3555e560f3d11a85ebff9a2abe9d9cf6f7f10a8c93feda9503b2",
    "alertEntryPoint": "3e3ccd248652e8fce4674d0c5f3f30f2ddc63da277bfa0ff36ea9420e5dffd5e",
    "cartEstimated": "0ef32acb778fc9d300ac62dc784b664323f105af9c4a6eacabaa72d1f1a73b55",
    "cartItemV2": "d63a7fbddec89e5d7d9f36cc3f6ae40c719891e01b70169d7ada8aad11e5e0f0",
}


def _harvest(found: dict[str, str]):
    def handler(req):
        with contextlib.suppress(Exception):
            if "graphql" not in req.url.lower() or req.method != "POST" or not req.post_data:
                return
            body = req.post_data
            docs = json.loads(body) if body.lstrip().startswith("[") else [json.loads(body)]
            for doc in docs:
                op = doc.get("operationName")
                sha = (doc.get("extensions") or {}).get("persistedQuery", {}).get("sha256Hash")
                if op and sha:
                    found.setdefault(op, sha)

    return handler


def _click_first(page, selectors, label):
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.count() and el.is_visible():
                el.click(timeout=4000)
                print(f"  {label}: {sel}")
                return True
        except Exception:
            continue
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cdp", default="http://localhost:9222", help="Chrome DevTools endpoint")
    ap.add_argument("--no-cart", action="store_true", help="skip the cart-quantity nudge")
    args = ap.parse_args()

    found: dict[str, str] = {}
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(args.cdp)
        if not browser.contexts:
            raise SystemExit("No browser context — is Chrome running with --remote-debugging-port?")
        ctx = browser.contexts[0]
        ctx.on("request", _harvest(found))
        page = next((pg for pg in ctx.pages if "heb.com" in pg.url), None)
        if page is None:
            raise SystemExit("Open a heb.com tab (signed in) in the debugged Chrome first.")

        for name, url in [
            ("home", "https://www.heb.com/"),
            ("search", "https://www.heb.com/search?q=milk"),
            ("cart", "https://www.heb.com/cart"),
        ]:
            with contextlib.suppress(Exception):
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(4)
            print(f"[{name}] operations captured so far: {len(found)}")

        if not args.no_cart and "cartItemV2" not in found:
            print("[cart] nudging an item quantity +1/-1 to trigger cartItemV2…")
            if _click_first(page, [
                'button[aria-label*="ncrement"]', 'button[aria-label*="ncrease"]',
                'button[data-testid*="increment"]', 'button:has-text("+")',
            ], "increment"):
                time.sleep(4)
                _click_first(page, [
                    'button[aria-label*="ecrement"]', 'button[aria-label*="ecrease"]',
                    'button[data-testid*="decrement"]', 'button:has-text("-")',
                ], "decrement (restore)")
                time.sleep(3)

    print("\n# --- PERSISTED_QUERIES (paste the relevant lines into clients/graphql.py) ---")
    for op in sorted(found):
        changed = ""
        if op in CURRENT and CURRENT[op] != found[op]:
            changed = "   # CHANGED"
        elif op in CURRENT:
            changed = "   # unchanged"
        print(f'    "{op}": "{found[op]}",{changed}')

    stale = [op for op, h in CURRENT.items() if op in found and found[op] != h]
    print(
        f"\n# captured {len(found)} operations; "
        f"{len(stale)} known constant(s) changed: {stale or 'none'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
