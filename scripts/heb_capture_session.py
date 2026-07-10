#!/usr/bin/env python3
"""Capture a working HEB session from your real, logged-in Chrome profile.

This supersedes the isolated-``.heb-chrome-profile`` approach (which is never
signed in, so it always comes up cold and — being driven over the debug port on
a cold session — is hard-blocked by HEB's Imperva WAF with an ``errorCode 15``
page). Instead we use the profile you're actually signed into.

Flow (no browser automation the WAF can fingerprint as a cold bot, and your
Keychain master key is never handled here):

1. Find the Chrome profile with HEB cookies (or pass ``--profile``).
2. Copy just its session files into a scratch user-data-dir, so the debug port
   binds cleanly and your live Chrome is untouched.
3. Launch Chrome against the copy — Chrome decrypts the cookies internally, in
   your own security context.
4. Navigate heb.com with that valid session. It passes the WAF (a cold/empty
   profile does not), which also lets the page mint/renew reese84 and fire the
   GraphQL traffic we harvest hashes from.
5. Write ``auth.json`` (cookies + localStorage incl. reese84) and refresh the
   persisted-query cache — the running MCP picks the hashes up with no restart
   thanks to ``PersistedQueryManager.reload_if_changed``.

Usage::

    uv run --extra browser python scripts/heb_capture_session.py [--profile "Profile 1"]

Exit codes: 0 = captured; 2 = WAF blocked or no HEB profile found.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

from texas_grocery_mcp.clients.graphql import PERSISTED_QUERIES
from texas_grocery_mcp.clients.persisted_queries import (
    PersistedQueryManager,
    extract_persisted_hashes,
)

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_DIR = os.path.expanduser("~/Library/Application Support/Google/Chrome")
DEFAULT_AUTH = os.path.expanduser("~/.texas-grocery-mcp/auth.json")
PORT = 9222
# In-page JS to dump localStorage as [{name, value}] (reese84 lives here).
_LS_JS = "() => Object.keys(localStorage).map(k => ({name:k, value:localStorage.getItem(k)}))"


def _heb_cookie_count(profile_dir: str) -> int:
    ck = os.path.join(profile_dir, "Cookies")
    if not os.path.exists(ck):
        return 0
    tmp = tempfile.mktemp(suffix=".db")
    try:
        shutil.copy(ck, tmp)
        con = sqlite3.connect(tmp)
        n = con.execute(
            "SELECT count(*) FROM cookies WHERE host_key LIKE '%heb.com%'"
        ).fetchone()[0]
        con.close()
        return int(n)
    except Exception:
        return 0
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def detect_profile() -> str | None:
    """Return the profile directory name with the most HEB cookies."""
    best, best_n = None, 0
    for name in sorted(os.listdir(CHROME_DIR)):
        if name != "Default" and not name.startswith("Profile "):
            continue
        n = _heb_cookie_count(os.path.join(CHROME_DIR, name))
        if n > best_n:
            best, best_n = name, n
    return best


def build_copy(profile: str, scratch: str) -> None:
    default = os.path.join(scratch, "Default")
    os.makedirs(default, exist_ok=True)
    shutil.copy(os.path.join(CHROME_DIR, "Local State"), os.path.join(scratch, "Local State"))
    src = os.path.join(CHROME_DIR, profile)
    shutil.copy(os.path.join(src, "Cookies"), os.path.join(default, "Cookies"))
    shutil.copytree(os.path.join(src, "Local Storage"), os.path.join(default, "Local Storage"))


def _port_up() -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=2)
        return True
    except Exception:
        return False


def _reese_fresh(items: list[dict]) -> bool:
    for it in items:
        if it["name"] == "reese84":
            with contextlib.suppress(Exception):
                return json.loads(it["value"]).get("renewTime", 0) / 1000 > time.time()
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", help="Chrome profile dir (auto-detected if omitted)")
    ap.add_argument("--auth-path", default=DEFAULT_AUTH)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    profile = args.profile or detect_profile()
    if not profile:
        print("No Chrome profile with HEB cookies found. Sign into heb.com in Chrome first.")
        return 2
    print(f"Using profile: {profile}")

    scratch = tempfile.mkdtemp(prefix="heb-session-")
    build_copy(profile, scratch)
    proc = subprocess.Popen(
        [CHROME, f"--user-data-dir={scratch}", "--profile-directory=Default",
         f"--remote-debugging-port={PORT}", "--no-first-run", "--no-default-browser-check",
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(25):
        if _port_up():
            break
        time.sleep(1)

    known = set(PERSISTED_QUERIES)
    found: dict[str, str] = {}
    blocked = False
    cookies: list[dict] = []
    ls_items: list[dict] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
            ctx = browser.contexts[0]

            def harvest(req):
                with contextlib.suppress(Exception):
                    if "graphql" in req.url.lower() and req.method == "POST" and req.post_data:
                        for op, sha in extract_persisted_hashes(req.post_data, known).items():
                            found.setdefault(op, sha)

            ctx.on("request", harvest)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            for url in ("https://www.heb.com/", "https://www.heb.com/cart"):
                with contextlib.suppress(Exception):
                    page.goto(url, wait_until="networkidle", timeout=45000)
                time.sleep(5)

            body = page.evaluate("() => document.body.innerText.slice(0,300)")
            blocked = "errorCode" in body or "could not load" in body.lower()
            cookies = [c for c in ctx.cookies() if "heb.com" in c.get("domain", "")]
            ls_items = page.evaluate(_LS_JS)
    finally:
        proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=5)
        shutil.rmtree(scratch, ignore_errors=True)

    if blocked or not cookies:
        print("WAF blocked the session (or no cookies). Is the profile signed into heb.com?")
        return 2

    origins = [{"origin": "https://www.heb.com", "localStorage": ls_items}] if ls_items else []
    if os.path.exists(args.auth_path):
        shutil.copy(args.auth_path, args.auth_path + ".bak")
    os.makedirs(os.path.dirname(args.auth_path), exist_ok=True)
    with open(args.auth_path, "w") as f:
        json.dump({"cookies": cookies, "origins": origins}, f, indent=1)

    if found:
        mgr = PersistedQueryManager(seed_hashes=PERSISTED_QUERIES)
        mgr.update_hashes(found)
        mgr._last_discovery = time.time()
        mgr._save_cache()

    names = {c["name"] for c in cookies}
    print(f"auth.json written: {len(cookies)} cookies, {len(ls_items)} localStorage keys")
    print("auth cookies present:",
          [n for n in ("_session", "sat", "DYN_USER_ID") if n in names])
    reese_state = "FRESH" if _reese_fresh(ls_items) else "stale (token cookie may still be valid)"
    print("reese84 renewTime:", reese_state)
    print("persisted-query hashes refreshed:", sorted(found) or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
