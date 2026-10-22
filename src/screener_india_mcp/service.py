"""High-level operations used by both the MCP server and the CLI.

A company page is fetched once and reused for overview, statements,
shareholding, documents, earnings trend and red flags — so a full company
look-up costs ONE request to Screener.in (plus one each for peers and prices,
only when asked).
"""

from __future__ import annotations

import json
import re
from typing import Optional

from . import analytics, parsers, themes
from .client import Page, ScreenerClient
from .errors import NotFound, ParseError, ScreenerError

_SYMBOL = re.compile(r"^[A-Z0-9&\-\.]{1,20}$")
STATEMENTS = {
    "quarters": "quarters",
    "quarterly": "quarters",
    "profit_loss": "profit_loss",
    "profit-loss": "profit_loss",
    "pl": "profit_loss",
    "balance_sheet": "balance_sheet",
    "balance-sheet": "balance_sheet",
    "bs": "balance_sheet",
    "cash_flow": "cash_flow",
    "cash-flow": "cash_flow",
    "cf": "cash_flow",
    "ratios": "ratios_history",
}


class Screener:
    def __init__(self, client: Optional[ScreenerClient] = None):
        self.client = client or ScreenerClient()

    # ---------------------------------------------------------------- resolve
    def _norm(self, symbol: str) -> str:
        s = (symbol or "").strip().upper()
        if not s:
            raise ScreenerError("A stock symbol is required (NSE symbol like TCS, or BSE code like 500570).")
        return s

    def search(self, query: str, limit: int = 10) -> dict:
        page = self.client.fetch("/api/company/search/", params={"q": query.strip()}, kind="search", json_api=True)
        res = parsers.parse_search(page.body)[: max(1, limit)]
        return {"query": query, "results": res, "provenance": page.provenance()}

    def _company_page(self, symbol: str, view: str = "auto") -> tuple[str, Page, dict]:
        sym = self._norm(symbol)
        if not _SYMBOL.match(sym):
            hits = self.search(symbol, limit=1)["results"]
            if not hits or not hits[0].get("symbol"):
                raise NotFound("No Screener.in company matches '%s'." % symbol)
            sym = hits[0]["symbol"].upper()
        order = {"consolidated": ["consolidated/"], "standalone": [""]}.get(view, ["consolidated/", ""])
        last_err: Exception | None = None
        for suffix in order:
            try:
                page = self.client.fetch("/company/%s/%s" % (sym, suffix), kind="company")
            except NotFound as exc:
                last_err = exc
                continue
            if not parsers.page_has_company_data(page.text):
                last_err = ParseError("Screener.in page for %s had no company data." % sym)
                continue
            data = parsers.parse_company_page(page.text)
            if not data.get("view"):
                data["view"] = "consolidated" if suffix else "standalone"
            if suffix and view == "auto" and not data.get("quarters"):
                last_err = ParseError("No consolidated figures for %s." % sym)
                continue
            return sym, page, data
        raise last_err or NotFound("No Screener.in page for %s." % sym)

    def _prov(self, page: Page, data: dict) -> dict:
        return page.provenance(view=data.get("view"), units="₹ crore unless stated")

    # ---------------------------------------------------------------- company
    def overview(self, symbol: str, view: str = "auto") -> dict:
        sym, page, d = self._company_page(symbol, view)
        keep = ("name", "nse_symbol", "bse_code", "website", "about", "ratios", "classification",
                "pros", "cons", "growth", "benchmarks")
        out = {k: d.get(k) for k in keep}
        out["symbol"] = sym
        out["provenance"] = self._prov(page, d)
        return out

    def statement(self, symbol: str, statement: str = "profit_loss", view: str = "auto", periods: int = 0) -> dict:
        key = STATEMENTS.get(statement.strip().lower())
        if not key:
            raise ScreenerError("statement must be one of: quarters, profit_loss, balance_sheet, cash_flow, ratios")
        sym, page, d = self._company_page(symbol, view)
        table = d.get(key)
        if table and periods and periods > 0:
            n = periods
            table = {"periods": table["periods"][-n:],
                     "period_end_dates": (table.get("period_end_dates") or [])[-n:] or None,
                     "rows": {k: v[-n:] for k, v in table["rows"].items()}}
        return {"symbol": sym, "name": d.get("name"), "statement": key, "table": table,
                "provenance": self._prov(page, d)}

    def shareholding(self, symbol: str, period: str = "quarterly") -> dict:
        sym, page, d = self._company_page(symbol)
        sh = d.get("shareholding") or {}
        return {"symbol": sym, "name": d.get("name"), "period": period,
                "table": sh.get("yearly" if period.startswith("y") else "quarterly"),
                "unit": "percent of shares", "provenance": self._prov(page, d)}

    def documents(self, symbol: str, kind: str = "all", limit: int = 20) -> dict:
        sym, page, d = self._company_page(symbol)
        docs = d.get("documents") or {}
        if kind != "all":
            k = kind.strip().lower().replace(" ", "_")
            docs = {k: docs.get(k, [])}
        docs = {k: v[: max(1, limit)] for k, v in docs.items()}
        return {"symbol": sym, "name": d.get("name"), "documents": docs, "provenance": self._prov(page, d)}

    def earnings_trend(self, symbol: str, quarters: int = 8) -> dict:
        sym, page, d = self._company_page(symbol)
        out = analytics.earnings_trend(d, quarters)
        out.update(symbol=sym, name=d.get("name"), provenance=self._prov(page, d))
        return out

    def red_flags(self, symbol: str) -> dict:
        sym, page, d = self._company_page(symbol)
        out = analytics.red_flags(d)
        out.update(symbol=sym, name=d.get("name"), provenance=self._prov(page, d))
        return out

    def snapshot(self, symbol: str) -> dict:
        sym, page, d = self._company_page(symbol)
        return {
            "symbol": sym,
            "overview": {k: d.get(k) for k in ("name", "nse_symbol", "bse_code", "website", "about", "ratios",
                                               "classification", "pros", "cons", "growth")},
            "earnings_trend": analytics.earnings_trend(d, 8),
            "red_flags": analytics.red_flags(d),
            "shareholding_latest": _latest_column(d.get("shareholding", {}).get("quarterly")),
            "documents": {k: v[:5] for k, v in (d.get("documents") or {}).items()},
            "provenance": self._prov(page, d),
        }

    def compare(self, symbols: list[str]) -> dict:
        syms = [s for s in (symbols or []) if s and s.strip()]
        if not 2 <= len(syms) <= 6:
            raise ScreenerError("Give between 2 and 6 symbols to compare.")
        rows, errors = [], {}
        for s in syms:
            try:
                sym, page, d = self._company_page(s)
                row = analytics.comparison_row(sym, d)
                row["fetched_at"] = page.provenance()["fetched_at"]
                rows.append(row)
            except ScreenerError as exc:
                errors[s] = str(exc)
        return {"companies": rows, "errors": errors or None}

    # ---------------------------------------------------------------- other endpoints
    def peers(self, symbol: str) -> dict:
        sym, page, d = self._company_page(symbol)
        wid = d.get("warehouse_id")
        if not wid:
            raise ParseError("Could not find the peer-table id on the %s page." % sym)
        pp = self.client.fetch("/api/company/%s/peers/" % wid, kind="peers")
        out = parsers.parse_peers(pp.text)
        out.update(symbol=sym, name=d.get("name"), classification=d.get("classification"),
                   provenance=pp.provenance())
        return out

    def price_history(self, symbol: str, days: int = 365, metric: str = "price") -> dict:
        sym, page, d = self._company_page(symbol)
        cid = d.get("company_id")
        if not cid:
            raise ParseError("Could not find the chart id on the %s page." % sym)
        allowed = (30, 90, 180, 365, 1095, 1825, 3652, 10000)
        days = min(allowed, key=lambda a: abs(a - int(days)))
        q = {
            "price": "Price-DMA50-DMA200-Volume",
            "pe": "Price to Earning-Median PE-EPS",
            "margins": "GPM-OPM-NPM-Quarter Sales",
            "ev_ebitda": "EV Multiple-Median EV Multiple-EBITDA",
            "pb": "Price to book value-Median PBV-Book value",
            "mcap_sales": "Market Cap to Sales-Median Market Cap to Sales-Sales",
        }.get(metric.strip().lower())
        if not q:
            raise ScreenerError("metric must be one of: price, pe, margins, ev_ebitda, pb, mcap_sales")
        cp = self.client.fetch("/api/company/%s/chart/" % cid, params={"q": q, "days": days}, kind="chart",
                               json_api=True)
        series = parsers.parse_chart(cp.body)
        return {"symbol": sym, "name": d.get("name"), "days": days, "metric": metric, "series": series,
                "provenance": cp.provenance()}

    def run_screen(self, query: str, sort: str = "", order: str = "desc", limit: int = 25, page: int = 1) -> dict:
        params = {"query": query.strip(), "sort": sort, "order": order, "page": max(1, int(page))}
        pg = self.client.fetch("/screen/raw/", params=params, kind="screen", need_login=True)
        res = parsers.parse_screen_results(pg.text)
        res["companies"] = res["companies"][: max(1, min(int(limit), 50))]
        res.update(query=query, provenance=pg.provenance())
        return res

    def theme_screen(self, theme: str = "", limit: int = 25) -> dict:
        if not theme:
            return {"themes": themes.list_themes()}
        key = themes.match_theme(theme)
        if not key:
            return {"error": "Unknown theme '%s'." % theme, "themes": themes.list_themes()}
        desc, q = themes.THEMES[key]
        out = self.run_screen(q, limit=limit)
        out.update(theme=key, description=desc)
        return out

    def status(self) -> dict:
        return self.client.status()


def _latest_column(table: Optional[dict]) -> Optional[dict]:
    if not table:
        return None
    return {"period": table["periods"][-1] if table["periods"] else None,
            **{k: (v[-1] if v else None) for k, v in table["rows"].items()}}


def to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)
