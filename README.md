# Screener India MCP

**The rate-safe, source-traced Screener.in server for AI assistants.**

Ask Claude (or any MCP client) about Indian NSE/BSE companies and get Screener.in fundamentals —
ratios, 10-year statements, quarterly trends, shareholding, peers, price history, documents and
screens — without getting your network or account blocked, and with every number traceable to the
page it came from.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![MCP](https://img.shields.io/badge/MCP-read--only%20tools-green)

> **Personal research only.** Screener.in's terms allow personal, non-commercial viewing. This
> project is not affiliated with or endorsed by Screener.in / Mittal Analytics. It does not
> redistribute any Screener data; everything stays on your machine. Not investment advice.

---

## Why another Screener MCP?

There are already a few. This one exists because of what went wrong with them in real use:

| Problem with existing tools | What Screener India MCP does |
|---|---|
| Each process throttles itself, so two or three running together trip Screener's limits and get the network blocked | **One machine-wide governor**: every process shares one request spacing (≥ 2 s, default 3 s), one **daily budget** and one cool-down, enforced with a file lock |
| After a block they keep hammering, which makes the block longer | **Block-aware**: a refusal (HTTP 403/429/503 or a refused connection) starts a cool-down of 30 min → 2 h → 6 h → 24 h, and answers come from cache, clearly marked `stale` |
| Passwords sit in plain-text config, or an AI tool accepts the password in chat | **Log in once**: the password lives in your OS secure store (Windows Credential Manager / macOS Keychain / Linux Secret Service). There is **no tool that accepts a password**. Silent session expiry is detected and it logs in again by itself |
| "Red flags" means handing raw tables to the AI and hoping | **12 deterministic red-flag checks** with the evidence attached — same page, same answer, every time |
| Numbers with no source | Every response carries **provenance**: source URL, fetch time, cached/stale, consolidated vs standalone |
| Some tools expose shell commands, file writes or data syncs to the AI | **14 read-only tools** (annotated `readOnlyHint`), no file writes, no shell, no bulk mirroring |
| One company look-up = many page loads | A company page is fetched **once** and reused for overview, statements, trend, red flags, shareholding and documents |

## Tools

| Tool | What it gives | Requests |
|---|---|---|
| `company_snapshot` | Best first call: ratios, sector/industry, pros/cons, growth, 8-quarter trend, red flags, latest shareholding, recent documents | 1 |
| `company_overview` | Market cap, P/E, book value, ROCE, ROE, 52-week range, about, classification, compounded growth | 1 (shared) |
| `financial_statement` | Quarters, P&L, balance sheet, cash flow or ratios history as periods × rows | 1 (shared) |
| `earnings_trend` | Quarterly sales/profit/margin/EPS with YoY growth and accelerating / steady / decelerating | 1 (shared) |
| `red_flags` | 12 rule-based checks (cash conversion, receivable & inventory days, other income, leverage, debt vs sales, profit vs sales, falling returns, promoter selling, low tax, CWIP, share-capital increase) | 1 (shared) |
| `shareholding` | Promoter / FII / DII / public history, quarterly or yearly | 1 (shared) |
| `documents` | Announcements, annual reports, credit ratings, concall transcripts / presentations / recordings | 1 (shared) |
| `peers` | Industry peer table | +1 |
| `price_history` | Price with 50/200-DMA, volume and delivery %, or P/E, margins, EV/EBITDA, P/B, Mcap/Sales history | +1 |
| `compare_companies` | Side-by-side valuation, returns, margins and growth for 2–6 companies | 1 per company |
| `search_company` | Find the symbol from a name | 1 |
| `run_screen` | Any Screener query, e.g. `Return on capital employed > 20 AND Debt to equity < 0.3` (needs login) | 1 |
| `theme_screen` | 12 ready-made screens (quality compounders, earnings acceleration, margin expansion, turnaround…) (needs login) | 1 |
| `service_status` | Login state, requests used/left today, cool-down, cache | 0 |

"shared" = served from the same cached company page, so asking several of these costs one request.

## Install

```bash
pipx install screener-india-mcp        # or: uv tool install screener-india-mcp
```

Not on PyPI yet? Install from GitHub:

```bash
pipx install git+https://github.com/indrajitdaspiramal-dotcom/screener-india-mcp
```

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "screener-india": { "command": "screener-india-mcp" }
  }
}
```

### Claude Code

```bash
claude mcp add screener-india -- screener-india-mcp
```

Any other MCP client: run `screener-india-mcp` (stdio), or `screener-india-mcp serve --http`
for streamable HTTP on `127.0.0.1:8631`.

## Optional: log in once (for screens)

Company data works without an account. Screens need a (free) Screener.in login:

```bash
screener-india-mcp login        # asks for email, then the password with hidden typing
screener-india-mcp status       # shows login state and today's budget
screener-india-mcp logout       # removes it
```

The password goes straight into your OS keyring and is never printed, logged or sent anywhere
except Screener's own login form. When Screener ends the session, the server logs in again by itself.
Headless Linux without a keyring: set `SCREENER_EMAIL` and `SCREENER_PASSWORD` (less safe).

## Politeness settings

Environment variables can make the server **more** polite, never less:

| Variable | Default | Limit |
|---|---|---|
| `SCREENER_MIN_INTERVAL` | 3 s between requests | never below 2 s |
| `SCREENER_DAILY_BUDGET_ANON` | 40 requests/day without login | max 60 |
| `SCREENER_DAILY_BUDGET` | 300 requests/day with login | max 1000 |
| `SCREENER_STATE_DIR`, `SCREENER_CACHE_DIR` | OS defaults | — |

Pages are cached locally (company pages 6 h, prices 3 h, search 7 days). When the budget is spent
or Screener is cooling us down, cached answers are still served, marked `stale: true`.

## Using it as a library

```python
from screener_india_mcp.service import Screener

s = Screener()
snap = s.snapshot("TCS")
print(snap["overview"]["ratios"]["pe"], snap["red_flags"]["summary"])
```

Batch jobs share the same machine-wide governor as the MCP server, so a nightly script and an
assistant session can run side by side without tripping Screener's limits.

## Development

```bash
git clone https://github.com/indrajitdaspiramal-dotcom/screener-india-mcp
cd screener-india-mcp
pip install -e ".[dev]"
pytest
```

Tests use **synthetic** fixtures (invented company, invented numbers) that copy only the page
*structure*; no Screener.in content is stored in this repository. Tests never touch the network or
your real keyring.

## Acknowledgements

Ideas were drawn from earlier open-source work, with thanks:
[LogeshR15/screener-mcp](https://github.com/LogeshR15/screener-mcp) (MIT; the "table with the most
company links" approach to screen results),
[screener-ai-tool](https://pypi.org/project/screener-ai-tool/) (MIT; price-chart endpoint and
document lists) and the
[Printing Press screener CLI](https://github.com/mvanhorn/printing-press-library) (Apache-2.0;
quarterly trend idea). The code here is an independent implementation.

## License

MIT © 2026 Indrajit Das
