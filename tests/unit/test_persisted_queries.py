"""Tests for the PersistedQueryManager.

Tests verify:
1. Seed hashes are used by default
2. Discovered hashes override seeds
3. Hash discovery from JS bundles works correctly
4. Cache persistence to disk works
5. Integration: stale hash triggers discovery and retry
"""

import json
import time
from unittest.mock import patch

import httpx
import pytest
import respx
from httpx import Response

from texas_grocery_mcp.clients.persisted_queries import PersistedQueryManager

# ─── Fixtures ──────────────────────────────────────────────────────────────────


SEED_HASHES = {
    "cartEstimated": "aaa1111111111111111111111111111111111111111111111111111111111aaaa",
    "cartItemV2": "bbb2222222222222222222222222222222222222222222222222222222222bbbb",
    "StoreSearch": "ccc3333333333333333333333333333333333333333333333333333333333cccc",
}


@pytest.fixture
def cache_file(tmp_path):
    """Temporary cache file path."""
    return tmp_path / "pq_cache.json"


@pytest.fixture
def manager(cache_file):
    """Fresh manager with seed hashes and a temp cache file."""
    return PersistedQueryManager(seed_hashes=SEED_HASHES, cache_path=cache_file)


# ─── Hash Lookup Tests ─────────────────────────────────────────────────────────


def test_get_hash_returns_seed_when_no_discovered(manager):
    """get_hash should return the seed hash when nothing is discovered."""
    assert manager.get_hash("cartEstimated") == SEED_HASHES["cartEstimated"]
    assert manager.get_hash("cartItemV2") == SEED_HASHES["cartItemV2"]


def test_get_hash_returns_none_for_unknown_operation(manager):
    """get_hash should return None for operations not in seed."""
    assert manager.get_hash("nonExistentOp") is None


def test_get_hash_prefers_discovered_over_seed(manager):
    """Discovered hashes should override seed hashes."""
    fresh_hash = "ddd4444444444444444444444444444444444444444444444444444444444dddd"
    manager.update_hash("cartEstimated", fresh_hash)

    assert manager.get_hash("cartEstimated") == fresh_hash
    assert manager.get_hash("cartEstimated") != SEED_HASHES["cartEstimated"]


def test_all_hashes_merges_discovered_and_seed(manager):
    """all_hashes should merge discovered over seed."""
    fresh = "eee5555555555555555555555555555555555555555555555555555555555eeee"
    manager.update_hash("cartEstimated", fresh)

    merged = manager.all_hashes
    assert merged["cartEstimated"] == fresh
    assert merged["cartItemV2"] == SEED_HASHES["cartItemV2"]  # seed still there
    assert merged["StoreSearch"] == SEED_HASHES["StoreSearch"]


# ─── Hash Update Tests ─────────────────────────────────────────────────────────


def test_update_hash_persists_to_disk(manager, cache_file):
    """update_hash should save to the cache file."""
    fresh = "fff6666666666666666666666666666666666666666666666666666666666ffff"
    manager.update_hash("cartItemV2", fresh)

    assert cache_file.exists()
    data = json.loads(cache_file.read_text())
    assert "cartItemV2" in data["hashes"]
    assert data["hashes"]["cartItemV2"] == fresh


def test_update_hash_ignores_unknown_operations(manager):
    """update_hash should ignore operations not in the seed."""
    manager.update_hash("randomOp", "a" * 64)
    assert "randomOp" not in manager.all_hashes


def test_update_hashes_bulk_update(manager):
    """update_hashes should update multiple hashes at once."""
    fresh1 = "1" * 64
    fresh2 = "2" * 64

    count = manager.update_hashes({
        "cartEstimated": fresh1,
        "cartItemV2": fresh2,
        "unknownOp": "3" * 64,  # Should be ignored
    })

    assert count == 2  # Only 2 known operations updated
    assert manager.get_hash("cartEstimated") == fresh1
    assert manager.get_hash("cartItemV2") == fresh2


# ─── Cache Persistence Tests ───────────────────────────────────────────────────


def test_cache_loads_from_disk(cache_file):
    """Manager should load discovered hashes from cache on init."""
    # Write a cache file
    cache_data = {
        "hashes": {"cartEstimated": "9" * 64},
        "last_discovery": time.time(),
    }
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(cache_data))

    # Create a new manager that should load the cache
    mgr = PersistedQueryManager(seed_hashes=SEED_HASHES, cache_path=cache_file)

    assert mgr.get_hash("cartEstimated") == "9" * 64
    assert mgr.is_cache_fresh()


def test_cache_freshness_check(manager):
    """is_cache_fresh should return False for empty cache."""
    assert not manager.is_cache_fresh()

    manager.update_hash("cartEstimated", "7" * 64)
    manager._last_discovery = time.time()
    assert manager.is_cache_fresh()


def test_cache_corrupt_file_is_handled(cache_file):
    """Corrupt cache file should not crash."""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("NOT VALID JSON {{{")

    mgr = PersistedQueryManager(seed_hashes=SEED_HASHES, cache_path=cache_file)
    # Should fall back to seed hashes
    assert mgr.get_hash("cartEstimated") == SEED_HASHES["cartEstimated"]


def test_reload_if_changed_picks_up_out_of_band_write(manager, cache_file):
    """A hash refreshed on disk after init is picked up without a restart."""
    # Nothing on disk yet, so the manager is serving the seed hash.
    assert manager.get_hash("cartEstimated") == SEED_HASHES["cartEstimated"]

    # Simulate scripts/refresh_persisted_hashes.py writing a fresh hash.
    fresh = "f" * 64
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"hashes": {"cartEstimated": fresh},
                                      "last_discovery": time.time()}))

    assert manager.reload_if_changed() is True
    assert manager.get_hash("cartEstimated") == fresh


def test_reload_if_changed_noop_when_unchanged(manager, cache_file):
    """reload_if_changed returns False when the file mtime hasn't advanced."""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    manager.update_hash("cartEstimated", "9" * 64)  # writes + records mtime
    assert manager.reload_if_changed() is False


def test_reload_if_changed_false_when_no_file(manager):
    """reload_if_changed is a safe no-op when the cache file doesn't exist."""
    assert manager.reload_if_changed() is False


# ─── JS Bundle Scanning Tests ──────────────────────────────────────────────────


def test_scan_bundle_finds_hash_near_operation_name(manager):
    """_scan_bundle should find hashes near known operation names."""
    # Simulate a JS bundle snippet where the operation name is near a hash
    js_content = '''
    var query = {
        operationName: "cartEstimated",
        extensions: {
            persistedQuery: {
                version: 1,
                sha256Hash: "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
            }
        }
    };
    '''

    discovered = {}
    manager._scan_bundle(js_content, set(SEED_HASHES.keys()), discovered)

    assert "cartEstimated" in discovered
    assert discovered["cartEstimated"] == "abcdef0123456789" * 4


def test_scan_bundle_finds_hash_in_reverse_order(manager):
    """_scan_bundle should find hashes even when hash precedes the operation name."""
    js_content = '''
    "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
    operationName: "cartItemV2"
    '''

    discovered = {}
    manager._scan_bundle(js_content, set(SEED_HASHES.keys()), discovered)

    assert "cartItemV2" in discovered


def test_scan_bundle_ignores_all_zero_hash(manager):
    """_scan_bundle should not accept all-zero hashes."""
    js_content = '''
    operationName: "cartEstimated"
    sha256Hash: "0000000000000000000000000000000000000000000000000000000000000000"
    '''

    discovered = {}
    manager._scan_bundle(js_content, set(SEED_HASHES.keys()), discovered)

    # Should not find the all-zero hash via the forward search
    if "cartEstimated" in discovered:
        assert discovered["cartEstimated"] != "0" * 64


# ─── Auto-Discovery Integration Tests ─────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_auto_discover_from_homepage(manager):
    """auto_discover should fetch homepage, find JS bundles, and extract hashes."""
    fresh_hash = "deadbeef" * 8  # 64 chars

    # Mock homepage with JS bundle reference
    homepage_html = (
        '<html><head>'
        '<script src="/_next/static/chunks/app-layout-abc123.js"></script>'
        '<script src="/_next/static/chunks/cart-page-def456.js"></script>'
        '</head><body>Hello</body></html>'
    )

    # Mock JS bundle with operation name + hash
    js_bundle = (
        'var q = { operationName: "cartEstimated", '
        'extensions: { persistedQuery: { sha256Hash: "'
        + fresh_hash
        + '" } } };'
    )

    respx.get(host="www.heb.com", path="/").mock(
        return_value=Response(200, text=homepage_html)
    )
    # Mock specific JS bundle URLs
    respx.get(host="www.heb.com", path="/_next/static/chunks/app-layout-abc123.js").mock(
        return_value=Response(200, text=js_bundle)
    )
    respx.get(host="www.heb.com", path="/_next/static/chunks/cart-page-def456.js").mock(
        return_value=Response(200, text=js_bundle)
    )

    async with httpx.AsyncClient() as client:
        discovered = await manager.auto_discover(client)

    assert "cartEstimated" in discovered
    assert discovered["cartEstimated"] == fresh_hash
    # Manager should now return the fresh hash
    assert manager.get_hash("cartEstimated") == fresh_hash


@pytest.mark.asyncio
@respx.mock
async def test_auto_discover_handles_waf_block(manager):
    """auto_discover should return empty dict when WAF blocks."""
    waf_block = json.dumps({
        "errorCode": "15",
        "description": "Blocked by WAF",
    })

    respx.get(host="www.heb.com", path="/").mock(
        return_value=Response(401, text=waf_block)
    )

    async with httpx.AsyncClient() as client:
        discovered = await manager.auto_discover(client)

    assert discovered == {}


@pytest.mark.asyncio
@respx.mock
async def test_auto_discover_handles_no_js_bundles(manager):
    """auto_discover should return empty dict when no JS bundles found."""
    respx.get(host="www.heb.com", path="/").mock(
        return_value=Response(200, text="<html><body>No scripts here</body></html>")
    )

    async with httpx.AsyncClient() as client:
        discovered = await manager.auto_discover(client)

    assert discovered == {}


# ─── GraphQL Client Integration Tests ──────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_stale_hash_triggers_discovery_and_retry():
    """When server returns PersistedQueryNotFound, client should auto-discover and retry."""
    from unittest.mock import patch as mock_patch

    from texas_grocery_mcp.clients.graphql import HEBGraphQLClient

    fresh_hash = "coffee" + "0" * 58  # 64 chars

    client = HEBGraphQLClient()

    # First call: server says PersistedQueryNotFound
    not_found_response = {
        "errors": [{"message": "PersistedQueryNotFound"}]
    }

    # Second call: success with fresh hash
    success_response = {
        "data": {"cartEstimated": {"items": [], "total": 0}}
    }

    call_count = [0]

    def graphql_responder(request):
        call_count[0] += 1
        if call_count[0] == 1:
            return Response(200, json=not_found_response)
        return Response(200, json=success_response)

    respx.post(host="www.heb.com", path="/graphql").mock(side_effect=graphql_responder)

    # Mock auto_discover to return the fresh hash (discovery itself is
    # tested separately in test_auto_discover_from_homepage)
    async def mock_discover(_client, **kw):
        client._pq_manager.update_hash("cartEstimated", fresh_hash)
        return {"cartEstimated": fresh_hash}

    with mock_patch.object(
        client._pq_manager, "auto_discover", side_effect=mock_discover
    ):
        result = await client._execute_persisted_query(
            "cartEstimated", {"userIsLoggedIn": True}
        )

    # Should have retried and gotten success
    assert "cartEstimated" in result
    assert call_count[0] >= 2  # At least 2 calls (initial + retry)

    # Manager should now have the fresh hash cached
    assert client._pq_manager.get_hash("cartEstimated") == fresh_hash


@pytest.mark.asyncio
@respx.mock
async def test_stale_hash_reloads_cache_and_retries(tmp_path):
    """An out-of-band cache refresh is picked up on the recovery path — no restart,
    and without relying on HTTP auto-discovery."""
    from unittest.mock import patch as mock_patch

    from texas_grocery_mcp.clients.graphql import HEBGraphQLClient

    client = HEBGraphQLClient()
    mgr = client._pq_manager
    cache_path = tmp_path / "pq_cache.json"
    mgr._cache_path = cache_path
    mgr._cache_mtime = 0.0
    mgr._discovered = {"cartEstimated": "a" * 64}  # stale in-memory hash

    fresh_hash = "b" * 64
    # Simulate scripts/refresh_persisted_hashes.py writing a fresh hash to disk.
    cache_path.write_text(json.dumps(
        {"hashes": {"cartEstimated": fresh_hash}, "last_discovery": time.time()}
    ))

    call_count = [0]

    def graphql_responder(request):
        call_count[0] += 1
        if call_count[0] == 1:
            return Response(200, json={"errors": [{"message": "PersistedQueryNotFound"}]})
        return Response(200, json={"data": {"cartEstimated": {"items": []}}})

    respx.post(host="www.heb.com", path="/graphql").mock(side_effect=graphql_responder)

    # Force HTTP discovery to find nothing, proving the reload is what recovered.
    async def empty_discover(_client, **kw):
        return {}

    with mock_patch.object(mgr, "auto_discover", side_effect=empty_discover):
        result = await client._execute_persisted_query("cartEstimated", {})

    assert "cartEstimated" in result
    assert call_count[0] >= 2  # initial + retry with reloaded hash
    assert mgr.get_hash("cartEstimated") == fresh_hash


@pytest.mark.asyncio
@respx.mock
async def test_discovery_failure_raises_clear_error():
    """When auto-discovery fails, should raise PersistedQueryNotFoundError."""
    from texas_grocery_mcp.clients.graphql import (
        HEBGraphQLClient,
        PersistedQueryNotFoundError,
    )

    client = HEBGraphQLClient()

    not_found_response = {
        "errors": [{"message": "PersistedQueryNotFound"}]
    }

    # Mock: GraphQL returns not-found, homepage returns WAF block
    respx.post(host="www.heb.com", path="/graphql").mock(
        return_value=Response(200, json=not_found_response)
    )
    respx.get(host="www.heb.com", path="/").mock(
        return_value=Response(401, text=json.dumps({"errorCode": "15"}))
    )

    with pytest.raises(PersistedQueryNotFoundError):
        await client._execute_persisted_query(
            "cartEstimated", {"userIsLoggedIn": True}
        )


# ─── Browser-traffic discovery (extract_persisted_hashes) ──────────────────────


def test_extract_persisted_hashes_single():
    """Extracts an operation→hash pair from a single GraphQL request body."""
    from texas_grocery_mcp.clients.persisted_queries import extract_persisted_hashes

    body = json.dumps(
        {
            "operationName": "cartItemV2",
            "variables": {"quantity": 1},
            "extensions": {"persistedQuery": {"version": 1, "sha256Hash": "d" * 64}},
        }
    )
    out = extract_persisted_hashes(body, {"cartItemV2", "cartEstimated"})
    assert out == {"cartItemV2": "d" * 64}


def test_extract_persisted_hashes_batched_and_filtered():
    """Handles batched bodies and ignores operations outside known_ops."""
    from texas_grocery_mcp.clients.persisted_queries import extract_persisted_hashes

    body = json.dumps(
        [
            {"operationName": "cartEstimated",
             "extensions": {"persistedQuery": {"sha256Hash": "a" * 64}}},
            {"operationName": "SomeUnknownOp",
             "extensions": {"persistedQuery": {"sha256Hash": "b" * 64}}},
        ]
    )
    out = extract_persisted_hashes(body, {"cartEstimated"})
    assert out == {"cartEstimated": "a" * 64}


def test_extract_persisted_hashes_ignores_malformed():
    """Malformed bodies / missing hashes yield an empty dict, not an error."""
    from texas_grocery_mcp.clients.persisted_queries import extract_persisted_hashes

    assert extract_persisted_hashes("not json", {"cartEstimated"}) == {}
    assert extract_persisted_hashes(json.dumps({"operationName": "cartEstimated"}),
                                    {"cartEstimated"}) == {}


def test_discover_via_browser_persists_when_playwright_missing(tmp_path):
    """Without playwright the method degrades gracefully to an empty result."""
    mgr = PersistedQueryManager(
        seed_hashes={"cartEstimated": "a" * 64},
        cache_path=tmp_path / "cache.json",
    )
    with patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
        assert mgr.discover_via_browser() == {}
