"""Persisted query hash discovery and auto-refresh.

HEB uses Apollo Persisted Queries (APQ) with SHA-256 hashes that change
when they deploy new frontend code. This module provides a mechanism to
automatically discover the current hashes from HEB's JavaScript bundles
when the hardcoded ones go stale.

The discovery flow:
1. Fetch HEB homepage HTML to find JS bundle URLs
2. Fetch each JS bundle and search for 64-char hex hashes near known
   GraphQL operation names
3. Cache discovered hashes to disk so they persist across restarts
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Default cache file location (next to auth.json)
_DEFAULT_CACHE_PATH = Path.home() / ".texas-grocery-mcp" / "persisted_query_cache.json"

# How long cached hashes are considered fresh (24 hours)
_CACHE_TTL_SECONDS = 86400

# Regex for 64-character lowercase hex SHA-256 hashes
_HASH_RE = re.compile(r"([a-f0-9]{64})")


class PersistedQueryManager:
    """Manages persisted query hashes with auto-discovery fallback.

    Usage:
        manager = PersistedQueryManager(seed_hashes=PERSISTED_QUERIES)
        hash_val = manager.get_hash("cartEstimated")
        # If hash is stale, manager.auto_discover(client) can refresh
    """

    def __init__(
        self,
        seed_hashes: dict[str, str],
        cache_path: Path | None = None,
    ):
        """Initialize with known/seed hashes.

        Args:
            seed_hashes: Initial hash mapping (from reverse engineering)
            cache_path: Where to persist discovered hashes. Defaults to
                        ~/.texas-grocery-mcp/persisted_query_cache.json
        """
        self._seed_hashes = dict(seed_hashes)
        self._cache_path = cache_path or _DEFAULT_CACHE_PATH
        self._discovered: dict[str, str] = {}
        self._last_discovery: float = 0.0
        self._load_cache()

    def get_hash(self, operation_name: str) -> str | None:
        """Get the best known hash for an operation.

        Priority: discovered (fresh) > seed (hardcoded).

        Args:
            operation_name: The GraphQL operation name

        Returns:
            The SHA-256 hash, or None if unknown
        """
        # Discovered hashes take priority (they're fresher)
        if operation_name in self._discovered:
            return self._discovered[operation_name]
        return self._seed_hashes.get(operation_name)

    def update_hash(self, operation_name: str, hash_value: str) -> None:
        """Update a single discovered hash and persist to cache.

        Args:
            operation_name: The GraphQL operation name
            hash_value: The new SHA-256 hash
        """
        if operation_name not in self._seed_hashes:
            logger.debug(
                "Ignoring hash for unknown operation %s", operation_name
            )
            return

        old = self._discovered.get(operation_name)
        if old != hash_value:
            logger.info(
                "Updating persisted query hash for %s: %s... -> %s...",
                operation_name,
                (old or "none")[:12],
                hash_value[:12],
            )

        self._discovered[operation_name] = hash_value
        self._save_cache()

    def update_hashes(self, hashes: dict[str, str]) -> int:
        """Bulk update discovered hashes.

        Args:
            hashes: Mapping of operation names to hashes

        Returns:
            Number of hashes actually updated (only known operations)
        """
        count = 0
        for name, value in hashes.items():
            if name in self._seed_hashes:
                self._discovered[name] = value
                count += 1
        if count:
            self._save_cache()
        return count

    @property
    def all_hashes(self) -> dict[str, str]:
        """Return the merged hash mapping (discovered overrides seed)."""
        merged = dict(self._seed_hashes)
        merged.update(self._discovered)
        return merged

    def is_cache_fresh(self, max_age_seconds: int = _CACHE_TTL_SECONDS) -> bool:
        """Check if the discovered cache is still fresh."""
        if not self._discovered:
            return False
        return (time.time() - self._last_discovery) < max_age_seconds

    async def auto_discover(
        self,
        client: httpx.AsyncClient,
        homepage_url: str = "https://www.heb.com",
    ) -> dict[str, str]:
        """Discover current persisted query hashes from HEB's JS bundles.

        Fetches the homepage, finds JS bundle URLs, then searches each
        bundle for 64-char hex hashes near known operation names.

        Args:
            client: An authenticated httpx AsyncClient
            homepage_url: HEB homepage URL

        Returns:
            Dict of {operation_name: hash} for discovered hashes
        """
        logger.info("Starting persisted query hash auto-discovery...")

        # Step 1: Fetch homepage to find JS bundle URLs
        try:
            resp = await client.get(homepage_url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Failed to fetch homepage for discovery: %s", e)
            return {}

        html = resp.text

        # Check for WAF block
        if "errorCode" in html and len(html) < 2000:
            logger.warning("WAF block detected during hash discovery")
            return {}

        # Find JS bundle URLs
        js_urls: set[str] = set()
        # Pattern: src="/_next/static/..."
        for match in re.finditer(r'src="(/_next/static/[^"]+\.js)"', html):
            js_urls.add(f"https://www.heb.com{match.group(1)}")
        # Pattern: "/_next/static/chunks/..."
        for match in re.finditer(r'"(/_next/static/chunks/[^"]+\.js)"', html):
            js_urls.add(f"https://www.heb.com{match.group(1)}")
        # Absolute URLs
        for match in re.finditer(
            r'"(https://www\.heb\.com/_next/static/[^"]+\.js)"', html
        ):
            js_urls.add(match.group(1))

        logger.info("Found %d JS bundles to scan", len(js_urls))

        if not js_urls:
            logger.warning("No JS bundles found in homepage HTML")
            return {}

        # Step 2: Scan each JS bundle for hashes
        discovered: dict[str, str] = {}
        known_ops = set(self._seed_hashes.keys())

        for url in sorted(js_urls):
            try:
                resp = await client.get(
                    url, headers={"Accept": "*/*", "Referer": homepage_url}
                )
                if resp.status_code != 200:
                    continue

                content = resp.text
                self._scan_bundle(content, known_ops, discovered)

                if len(discovered) >= len(known_ops):
                    break  # Found all operations

            except httpx.HTTPError:
                continue

        # Step 3: Update internal state
        if discovered:
            self.update_hashes(discovered)
            self._last_discovery = time.time()
            logger.info(
                "Auto-discovered %d/%d persisted query hashes",
                len(discovered),
                len(known_ops),
            )

        return discovered

    def _scan_bundle(
        self,
        content: str,
        known_ops: set[str],
        discovered: dict[str, str],
    ) -> None:
        """Scan a JS bundle content for operation→hash pairs.

        Looks for 64-char hex hashes and checks nearby text for known
        GraphQL operation names.

        Args:
            content: JS bundle text content
            known_ops: Set of known operation names to look for
            discovered: Dict to populate with findings
        """
        # Find all 64-char hex hashes and check context for operation names
        for match in _HASH_RE.finditer(content):
            the_hash = match.group(1)

            # Skip if it's clearly not a query hash (all zeros, etc.)
            if the_hash == "0" * 64:
                continue

            # Look at surrounding context (±200 chars)
            start = max(0, match.start() - 200)
            end = min(len(content), match.end() + 200)
            context = content[start:end]

            for op in known_ops:
                if op in context and op not in discovered:
                    discovered[op] = the_hash
                    logger.info("Discovered hash for %s: %s...", op, the_hash[:16])

        # Also try the reverse: find operation names and look for nearby hashes
        for op in known_ops:
            if op in discovered:
                continue
            for match in re.finditer(re.escape(op), content):
                # Look in a window after the operation name
                window = content[match.start():match.start() + 300]
                hash_match = _HASH_RE.search(window)
                if hash_match and hash_match.group(1) != "0" * 64:
                    discovered[op] = hash_match.group(1)
                    logger.info(
                        "Discovered hash for %s (forward): %s...",
                        op,
                        hash_match.group(1)[:16],
                    )
                    break

    def _load_cache(self) -> None:
        """Load discovered hashes from disk cache."""
        try:
            if self._cache_path.exists():
                data = json.loads(self._cache_path.read_text())
                self._discovered = data.get("hashes", {})
                self._last_discovery = data.get("last_discovery", 0.0)
                logger.info(
                    "Loaded %d cached persisted query hashes",
                    len(self._discovered),
                )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load hash cache: %s", e)

    def _save_cache(self) -> None:
        """Persist discovered hashes to disk."""
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(
                    {
                        "hashes": self._discovered,
                        "last_discovery": self._last_discovery,
                    },
                    indent=2,
                )
            )
        except OSError as e:
            logger.warning("Failed to save hash cache: %s", e)
