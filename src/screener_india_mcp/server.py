"""The MCP server. Every tool is read-only: no tool writes files, runs commands,
or accepts a password."""

from __future__ import annotations

import functools
from typing import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .errors import ScreenerError
from .service import Screener

INSTRUCTIONS = (
    "Indian (NSE/BSE) company data from Screener.in for personal research. "
    "Money values are in ₹ crore unless a field says otherwise; growth and margins are percentages. "
    "Every answer carries `provenance` (source page, fetch time, cached/stale, consolidated vs standalone) — "
    "cite it, and say so when data is stale. The server is deliberately slow and has a small daily request "
    "budget so it never gets the user blocked: prefer `company_snapshot` (one request) over many separate calls, "
    "and reuse answers you already have. If a tool returns `error_type: Blocked` or `BudgetExhausted`, tell the "
    "user and do not retry in a loop. Screens need a Screener.in login, which the user sets up once in a "
    "terminal with `screener-india-mcp login`; never ask the user for their password in chat."
)

mcp = FastMCP("screener-india", instructions=INSTRUCTIONS)
_svc: Screener | None = None
RO = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)


def svc() -> Screener:
    global _svc
    if _svc is None:
        _svc = Screener()
    return _svc


def _safe(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except ScreenerError as exc:
            return exc.to_dict()
    return wrapper


@mcp.tool(annotations=RO)
@_safe
def search_company(query: str, limit: int = 10) -> dict:
    """Find a company's Screener.in symbol from its name or part of its ticker (e.g. "caplin", "hdfc bank")."""
    return svc().search(query, limit)


@mcp.tool(annotations=RO)
@_safe
def company_snapshot(symbol: str) -> dict:
    """Best first call. One request gives: key ratios, sector/industry, pros/cons, compounded growth,
    8-quarter earnings trend, deterministic red-flag checks, latest shareholding and recent documents.
    `symbol` = NSE symbol (TCS) or BSE code (500570)."""
    return svc().snapshot(symbol)


@mcp.tool(annotations=RO)
@_safe
def company_overview(symbol: str, view: str = "auto") -> dict:
    """Key ratios (market cap, P/E, book value, ROCE, ROE, 52-week range…), about, sector/industry,
    pros/cons and 10/5/3-year compounded growth. view: auto | consolidated | standalone."""
    return svc().overview(symbol, view)


@mcp.tool(annotations=RO)
@_safe
def financial_statement(symbol: str, statement: str = "profit_loss", view: str = "auto", periods: int = 0) -> dict:
    """A full statement as periods × rows. statement: quarters | profit_loss | balance_sheet | cash_flow | ratios.
    periods: keep only the latest N columns (0 = all)."""
    return svc().statement(symbol, statement, view, periods)


@mcp.tool(annotations=RO)
@_safe
def earnings_trend(symbol: str, quarters: int = 8) -> dict:
    """Quarterly sales/profit/margin/EPS with year-on-year growth and whether growth is accelerating,
    steady or decelerating."""
    return svc().earnings_trend(symbol, quarters)


@mcp.tool(annotations=RO)
@_safe
def red_flags(symbol: str) -> dict:
    """Twelve fixed, explainable checks on reported numbers: cash conversion, debtor/inventory days,
    other-income share, leverage, debt vs sales growth, profit vs sales growth, falling returns,
    promoter selling, low tax, CWIP build-up, share-capital increase. Each with evidence."""
    return svc().red_flags(symbol)


@mcp.tool(annotations=RO)
@_safe
def shareholding(symbol: str, period: str = "quarterly") -> dict:
    """Promoter / FII / DII / government / public holding history. period: quarterly | yearly."""
    return svc().shareholding(symbol, period)


@mcp.tool(annotations=RO)
@_safe
def documents(symbol: str, kind: str = "all", limit: int = 20) -> dict:
    """Links to exchange announcements, annual reports, credit ratings and concall transcripts /
    presentations / recordings. kind: all | announcements | annual_reports | credit_ratings | concalls."""
    return svc().documents(symbol, kind, limit)


@mcp.tool(annotations=RO)
@_safe
def peers(symbol: str) -> dict:
    """Peer comparison table for the company's industry (price, P/E, market cap, quarterly growth, ROCE)."""
    return svc().peers(symbol)


@mcp.tool(annotations=RO)
@_safe
def price_history(symbol: str, days: int = 365, metric: str = "price") -> dict:
    """Daily history. metric: price (with 50/200-day averages and volume) | pe | margins | ev_ebitda | pb |
    mcap_sales. days snaps to 30, 90, 180, 365, 1095, 1825, 3652 or 10000."""
    return svc().price_history(symbol, days, metric)


@mcp.tool(annotations=RO)
@_safe
def compare_companies(symbols: list[str]) -> dict:
    """Side-by-side valuation, returns, margins and growth for 2–6 companies."""
    return svc().compare(symbols)


@mcp.tool(annotations=RO)
@_safe
def run_screen(query: str, sort: str = "", order: str = "desc", limit: int = 25) -> dict:
    """Run a Screener.in query, e.g. "Return on capital employed > 20 AND Debt to equity < 0.3".
    Needs a Screener.in login set up once with `screener-india-mcp login`."""
    return svc().run_screen(query, sort, order, limit)


@mcp.tool(annotations=RO)
@_safe
def theme_screen(theme: str = "", limit: int = 25) -> dict:
    """Ready-made screens (quality compounders, earnings acceleration, margin expansion, turnaround…).
    Call with no theme to list them. Needs a login like run_screen."""
    return svc().theme_screen(theme, limit)


@mcp.tool(annotations=RO)
@_safe
def service_status() -> dict:
    """Login state, requests used/remaining today, cool-down status and cache size."""
    return svc().status()


def run(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8631) -> None:
    if transport == "stdio":
        mcp.run()
    else:
        mcp.settings.host = host
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
