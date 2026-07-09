#!/usr/bin/env python3
"""Refresh HEB's GraphQL persisted-query hashes from a live browser session.

HEB pins its GraphQL operations behind Automatic Persisted Query (APQ) hashes
and rotates them on deploy. When a hash goes stale the API rejects the request
with ``PersistedQueryNotFound`` and the affected tool (cart read/write, store
change, coupon clip) stops working. The pure-HTTP ``auto_discover`` can't
recover them on the current frontend (the hashes aren't hex literals in the
bundles), so this script captures them the reliable way: off the live GraphQL
traffic of a real Chrome you're signed into.

The captured hashes are written straight into ``PersistedQueryManager``'s cache
(``~/.texas-grocery-mcp/persisted_query_cache.json``), so the running server
picks them up with no code edit or release.

Why a real browser: HEB fronts the site with an Imperva WAF that hard-blocks a
freshly launched automation browser (an ``errorCode 15`` incident page, before
any login renders). Attaching to a normal Chrome you logged into yourself
sidesteps that — this script only *reads* the operation/hash pairs off the
network; your password never touches it.

Usage
-----
1. Launch Chrome with remote debugging on an isolated profile::

       "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
         --remote-debugging-port=9222 \\
         --user-data-dir="$HOME/.heb-chrome-profile"

   (Linux: ``google-chrome``; Windows: ``chrome.exe`` — same flags.)

2. In that window, sign in at https://www.heb.com and select a store. Keeping
   at least one item in the cart lets the script capture ``cartItemV2``.
3. Run this script::

       python scripts/refresh_persisted_hashes.py

Operations that only fire on account-mutating actions (``SelectPickupFulfillment``
on a store change, ``CouponClip`` on a clip) are captured only if you perform
those actions in the browser while the script is attached — it will not mutate
your account for you.
"""

from __future__ import annotations

import argparse

from texas_grocery_mcp.clients.graphql import PERSISTED_QUERIES
from texas_grocery_mcp.clients.persisted_queries import PersistedQueryManager


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cdp", default="http://localhost:9222", help="Chrome DevTools endpoint")
    ap.add_argument("--no-cart", action="store_true", help="skip the cart-quantity nudge")
    args = ap.parse_args()

    manager = PersistedQueryManager(seed_hashes=PERSISTED_QUERIES)
    found = manager.discover_via_browser(cdp_url=args.cdp, nudge_cart=not args.no_cart)

    if not found:
        print(
            "No hashes captured. Is Chrome running with --remote-debugging-port "
            "and signed in at heb.com? (Playwright required: pip install '.[browser]')"
        )
        return 1

    print(f"Captured and cached {len(found)} operation hash(es):")
    for op in sorted(found):
        seed = PERSISTED_QUERIES.get(op)
        state = "changed" if seed and seed != found[op] else "unchanged"
        print(f"    {op}: {found[op]}   # {state}")
    print(f"\nWritten to {manager._cache_path}. The server will use these on next call.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
