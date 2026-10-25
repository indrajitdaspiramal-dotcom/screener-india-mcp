# Changelog

All notable changes are documented here (format: [Keep a Changelog](https://keepachangelog.com/)).

## [0.1.1] — 2026-10-25

### Fixed
- BSE-only and SME companies were "not found": Screener files them under the BSE scrip code
  (`/company/530215/`). A ticker that is not found is now retried with its BSE code (when the caller
  supplies one via `Screener.set_bse_codes`), then with Screener's own search — accepted only when the
  match is unambiguous (exact symbol/code, or a single result). Successful look-ups are remembered.
- A near-empty consolidated page could win over a full standalone page (e.g. 1 quarter and 0 years of
  results). When the consolidated page has fewer than 8 quarters or 5 years of results, the standalone
  page is fetched too and the one with more history is used (`view_note` says why).

### Added
- `history` on every company page: years of results, quarters, and `short` for genuinely new listings.

## [0.1.0] — 2026-10-23

### Added
- 14 read-only MCP tools: company snapshot, overview, financial statements, earnings trend,
  red flags, shareholding, documents, peers, price history, compare, search, run screen,
  theme screens, service status.
- Machine-wide politeness governor (shared request spacing, daily budget, escalating cool-down).
- Local page cache with stale fallback during cool-downs.
- Login once via the OS keyring, automatic re-login on silent session expiry; no password tool.
- Provenance on every answer (source URL, fetch time, cached/stale, consolidated/standalone).
- CLI: `serve`, `login`, `logout`, `status`, `get`.
