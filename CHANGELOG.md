# Changelog

All notable changes are documented here (format: [Keep a Changelog](https://keepachangelog.com/)).

## [0.1.0] — unreleased

### Added
- 14 read-only MCP tools: company snapshot, overview, financial statements, earnings trend,
  red flags, shareholding, documents, peers, price history, compare, search, run screen,
  theme screens, service status.
- Machine-wide politeness governor (shared request spacing, daily budget, escalating cool-down).
- Local page cache with stale fallback during cool-downs.
- Login once via the OS keyring, automatic re-login on silent session expiry; no password tool.
- Provenance on every answer (source URL, fetch time, cached/stale, consolidated/standalone).
- CLI: `serve`, `login`, `logout`, `status`, `get`.
