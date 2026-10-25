# Changelog

All notable changes are documented here (format: [Keep a Changelog](https://keepachangelog.com/)).

## [0.1.2] — 2026-10-26

### Changed
- A thin consolidated page (fewer than 8 quarters or 5 years) no longer gives way to the standalone page.
  The latest figures and ratios stay **consolidated** (subsidiaries included); older columns are filled
  from the standalone page. Every table now carries a `basis` list (`consolidated` / `standalone` per
  column) and the response says what was filled (`history_fill`).
- Earnings-trend YoY growth is never computed across the join (a consolidated quarter is not compared with
  a standalone one). Red-flag checks use one basis only: the consolidated columns when they hold at least
  4 years, otherwise the whole standalone page (`basis` in the result says which).
- A consolidated page too new to have trailing-12-month figures (fewer than 4 quarters or no full year)
  is not used as the main source, because its P/E and returns would be unreliable; the standalone page is.

### Fixed
- An out-of-date consolidated page (a company that stopped publishing consolidated results years ago) could
  be taken as the latest numbers — one real example ended in Dec 2017 with a P/E of 913. If the consolidated
  page's newest quarter is older than the standalone page's, or more than 9 months old, the standalone page
  is checked and used.
- Year-on-year growth now compares with the same period one year earlier, matched by date. Before, it took
  the column four places back, which for half-yearly (SME) reporters is two years earlier.

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
