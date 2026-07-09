# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Builds on the persisted-query auto-discovery work (#21) to make cart operations
work against the current HEB frontend.

### Fixed
- Refresh the stale `cartEstimated`, `cartItemV2`, and `ShopNavigation` seed
  hashes to current values, verified end-to-end (`cart_get` + `cart_add`
  succeed against a live session). The previous seeds were rejected with
  `PersistedQueryNotFound`.

### Added
- `PersistedQueryManager.discover_via_browser()` — captures current hashes
  from the live GraphQL traffic of a real Chrome (attached over CDP), which
  reliably recovers rotating mutation hashes (e.g. `cartItemV2`) that the HTTP
  bundle scan cannot: on the current frontend the hashes aren't emitted as hex
  literals near their operation names, so `auto_discover` finds nothing. Also
  passes HEB's Imperva WAF, which hard-blocks a freshly launched browser.
- `scripts/refresh_persisted_hashes.py` — CLI wrapper that runs browser
  discovery and writes the results into the manager's on-disk cache.
- `extract_persisted_hashes()` helper with unit tests.

## [0.1.2] - 2026-02-02

### Changed
- README redesign with emojis and improved formatting
- Feature tables for better readability
- Tools organized in clean tables

### Fixed
- Placeholder link in TROUBLESHOOTING.md

### Removed
- firebase-debug.log from repository

## [0.1.1] - 2026-02-02

### Added
- Project URLs in PyPI metadata (homepage, repository, issues, changelog)
- PyPI, license, and CI badges in README
- CONTRIBUTING.md, SECURITY.md documentation

### Fixed
- GitHub repository URL in README

## [0.1.0] - 2026-02-02

### Added

- Initial public release
- **Store Tools**
  - `store_search` - Find HEB stores by address or zip code
  - `store_change` - Set preferred store (syncs with HEB.com when authenticated)
  - `store_get_default` - Get current default store
- **Product Tools**
  - `product_search` - Search products by name with pricing and availability
  - `product_search_batch` - Search multiple products at once (up to 20 queries)
  - `product_get` - Get comprehensive product details (ingredients, nutrition, warnings, dietary attributes)
- **Cart Tools**
  - `cart_check_auth` - Check authentication status
  - `cart_get` - View cart contents
  - `cart_add` - Add item with human-in-the-loop confirmation
  - `cart_add_many` - Bulk add multiple items
  - `cart_add_with_retry` - Add item with automatic retry on failure
  - `cart_remove` - Remove item with confirmation
- **Coupon Tools**
  - `coupon_list` - List available digital coupons
  - `coupon_search` - Search coupons by keyword
  - `coupon_categories` - Get coupon category list
  - `coupon_clip` - Clip a coupon to your account
  - `coupon_clipped` - List your clipped coupons
- **Session Tools**
  - `session_status` - Check session health and token expiration
  - `session_refresh` - Refresh/login with embedded browser or Playwright MCP
  - `session_save_credentials` - Save credentials for auto-login (secure keyring storage)
  - `session_clear_credentials` - Remove saved credentials
  - `session_clear` - Clear saved session (logout)
- **Health Tools**
  - `health_live` - Liveness probe
  - `health_ready` - Readiness probe with component status
- Fast session refresh with embedded Playwright (~15 seconds)
- Human-in-the-loop confirmation for cart and coupon operations
- Request throttling to prevent rate limiting
- In-memory and Redis caching support
- Docker support with docker-compose
- CI/CD with GitHub Actions

[0.1.1]: https://github.com/mgwalkerjr95/texas-grocery-mcp/releases/tag/v0.1.1
[0.1.0]: https://github.com/mgwalkerjr95/texas-grocery-mcp/releases/tag/v0.1.0
