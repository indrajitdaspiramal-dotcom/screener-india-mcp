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


THIN_QUARTERS = 8          # a consolidated page with fewer quarters OR fewer P&L years than these is "thin":
THIN_YEARS = 5             # the standalone page is fetched too and the one with more history wins


MIN_PRIMARY_QUARTERS = 4  # below this a consolidated page has no trailing-12-month figures, so its P/E etc.
MIN_PRIMARY_YEARS = 1     # are unreliable and the standalone page is used as the main source instead
HISTORY_TABLES = ("quarters", "profit_loss", "balance_sheet", "cash_flow", "ratios_history")
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                        "nov", "dec"), 1)}


def _depth(d: dict) -> tuple[int, int]:
    """(P&L years, quarters) of a parsed company page."""
    def n(key):
        return len(((d.get(key) or {}).get("periods")) or [])
    return n("profit_loss"), n("quarters")


def _period_keys(table: dict) -> list[Optional[str]]:
    """'YYYY-MM' per column (from Screener's date keys, else the 'Mar 2024' label); None for TTM etc."""
    dates = table.get("period_end_dates") or [None] * len(table.get("periods") or [])
    out = []
    for label, date in zip(table.get("periods") or [], dates):
        if date and re.match(r"^\d{4}-\d{2}", str(date)):
            out.append(str(date)[:7])
            continue
        m = re.match(r"^\s*([A-Za-z]{3})[a-z]*\s+(\d{4})\s*$", str(label or ""))
        out.append("%s-%02d" % (m.group(2), _MONTHS[m.group(1).lower()]) if m and m.group(1).lower() in _MONTHS
                   else None)
    return out


def _backfill(cons: Optional[dict], stand: Optional[dict]) -> tuple[Optional[dict], int]:
    """Consolidated table with OLDER periods taken from the standalone table. Every column carries its basis
    ('consolidated' / 'standalone') so growth across the join is never read as like-for-like. Rows stay the
    consolidated row set. Returns (table, number of columns added)."""
    if not stand or not stand.get("periods"):
        if cons:
            cons = dict(cons, basis=["consolidated"] * len(cons["periods"]))
        return cons, 0
    if not cons or not cons.get("periods"):
        return dict(stand, basis=["standalone"] * len(stand["periods"])), len(stand["periods"])
    ckeys = [k for k in _period_keys(cons) if k]
    if not ckeys:
        return dict(cons, basis=["consolidated"] * len(cons["periods"])), 0
    first = min(ckeys)
    skeys = _period_keys(stand)
    take = [i for i, k in enumerate(skeys) if k and k < first]
    if not take:
        return dict(cons, basis=["consolidated"] * len(cons["periods"])), 0
    srows = {k.lower(): v for k, v in (stand.get("rows") or {}).items()}

    def pick(vals, i):
        return vals[i] if vals and i < len(vals) else None
    rows = {}
    for label, vals in (cons.get("rows") or {}).items():
        old = srows.get(label.lower())
        rows[label] = [pick(old, i) for i in take] + list(vals)
    sdates = stand.get("period_end_dates") or [None] * len(stand["periods"])
    cdates = cons.get("period_end_dates") or [None] * len(cons["periods"])
    dates = [sdates[i] if i < len(sdates) else None for i in take] + list(cdates)
    return {"periods": [stand["periods"][i] for i in take] + list(cons["periods"]),
            "period_end_dates": dates if any(dates) else None, "rows": rows,
            "basis": ["standalone"] * len(take) + ["consolidated"] * len(cons["periods"])}, len(take)


def _combine(cons: dict, stand: dict) -> dict:
    """Option B (25-Oct-2026): latest figures and ratios from the CONSOLIDATED page (subsidiaries included),
    older history filled from the STANDALONE page and labelled as such."""
    data = dict(cons)
    added = {}
    for key in HISTORY_TABLES:
        data[key], n = _backfill(cons.get(key), stand.get(key))
        if n:
            added[key] = n
    csh = (cons.get("shareholding") or {}).get("quarterly") or {}
    ssh = (stand.get("shareholding") or {}).get("quarterly") or {}
    if len(ssh.get("periods") or []) > len(csh.get("periods") or []):   # company-level, same on both pages
        data["shareholding"] = stand.get("shareholding")
    data["view"] = "consolidated"
    data["history_fill"] = {"from": "standalone", "columns_added": added}
    cy, cq = _depth(cons)
    data["view_note"] = ("latest figures and ratios are consolidated; the consolidated page has only %d quarters "
                         "and %d years, so older columns come from the standalone page (marked 'standalone' in "
                         "each table's basis; growth across the join is not like-for-like)" % (cq, cy))
    data["_standalone"] = stand
    return data


class Screener:
    def __init__(self, client: Optional[ScreenerClient] = None):
        self.client = client or ScreenerClient()
        self._codes: dict[str, str] = {}          # caller-supplied ticker -> BSE scrip code (fallback page)

    # ---------------------------------------------------------------- resolve
    def _norm(self, symbol: str) -> str:
        s = (symbol or "").strip().upper()
        if not s:
            raise ScreenerError("A stock symbol is required (NSE symbol like TCS, or BSE code like 500570).")
        return s

    def set_bse_codes(self, codes: dict) -> None:
        """Ticker -> BSE scrip code. Screener files BSE-only and many SME companies under the BSE code
        (/company/530215/), so a ticker that is not found is retried with its code."""
        for k, v in (codes or {}).items():
            if k and v and str(v).strip().isdigit():
                self._codes[str(k).strip().upper()] = str(v).strip()

    def _aliases_path(self):
        return self.client.s.state_dir / "aliases.json"

    def _aliases(self) -> dict:
        try:
            return json.loads(self._aliases_path().read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _remember(self, sym: str, slug: str) -> None:
        if sym == slug:
            return
        a = self._aliases()
        if a.get(sym) != slug:
            a[sym] = slug
            try:
                self._aliases_path().write_text(json.dumps(a, indent=1, sort_keys=True), encoding="utf-8")
            except Exception:
                pass

    def search(self, query: str, limit: int = 10) -> dict:
        page = self.client.fetch("/api/company/search/", params={"q": query.strip()}, kind="search", json_api=True)
        res = parsers.parse_search(page.body)[: max(1, limit)]
        return {"query": query, "results": res, "provenance": page.provenance()}

    def _search_slug(self, sym: str, name: str = "") -> Optional[str]:
        """Screener's own search, accepted ONLY when it is unambiguous (an exact symbol/code match, or a
        single result) — a wrong company is worse than no data."""
        code = self._codes.get(sym)
        for q in [x for x in (name, sym) if x]:
            hits = [h for h in self.search(q, limit=10)["results"] if h.get("symbol")]
            exact = [h for h in hits if h["symbol"].upper() in (sym, code)]
            if exact:
                return exact[0]["symbol"].upper()
            if len(hits) == 1:
                return hits[0]["symbol"].upper()
        return None

    def _fetch_view(self, slug: str, suffix: str) -> tuple[Page, dict]:
        page = self.client.fetch("/company/%s/%s" % (slug, suffix), kind="company")
        if not parsers.page_has_company_data(page.text):
            raise ParseError("Screener.in page for %s had no company data." % slug)
        data = parsers.parse_company_page(page.text)
        if not data.get("view"):
            data["view"] = "consolidated" if suffix else "standalone"
        return page, data

    def _load(self, slug: str, view: str) -> tuple[Page, dict]:
        """Fetch one company page. In 'auto' (born 25-Oct-2026 from a 91-holding test):
        * consolidated rich enough -> consolidated only (one request);
        * consolidated thin (< 8 quarters or < 5 years) -> also fetch standalone; keep the CONSOLIDATED latest
          figures and fill older columns from standalone, labelled per column (``basis``);
        * consolidated too new to have trailing-12-month figures (< 4 quarters or no full year, e.g. SGFIN with
          1 quarter) -> its P/E and returns are unreliable, so the standalone page is the main source;
        * no consolidated page / no consolidated figures -> standalone."""
        if view in ("consolidated", "standalone"):
            page, data = self._fetch_view(slug, "consolidated/" if view == "consolidated" else "")
            return page, self._stamp(data)
        cons: Optional[tuple[Page, dict]] = None
        last_err: Exception | None = None
        try:
            cons = self._fetch_view(slug, "consolidated/")
            if not cons[1].get("quarters"):
                cons, last_err = None, ParseError("No consolidated figures for %s." % slug)
        except (NotFound, ParseError) as exc:
            last_err = exc
        if cons is not None:
            cy, cq = _depth(cons[1])
            if cq >= THIN_QUARTERS and cy >= THIN_YEARS:
                return cons[0], self._stamp(cons[1])
        try:
            stand = self._fetch_view(slug, "")
        except (NotFound, ParseError) as exc:
            if cons is None:
                raise last_err or exc
            return cons[0], self._stamp(cons[1])
        if cons is None:
            return stand[0], self._stamp(stand[1])
        cy, cq = _depth(cons[1])
        sy, sq = _depth(stand[1])
        if sy <= cy and sq <= cq:
            return cons[0], self._stamp(cons[1])        # standalone adds nothing
        if cq < MIN_PRIMARY_QUARTERS or cy < MIN_PRIMARY_YEARS:
            data = stand[1]
            data["view_note"] = ("standalone used: the consolidated page has only %d quarters and %d years, too "
                                 "new for trailing-12-month figures" % (cq, cy))
            return stand[0], self._stamp(data)
        return cons[0], self._stamp(_combine(cons[1], stand[1]))

    @staticmethod
    def _stamp(data: dict) -> dict:
        years, quarters = _depth(data)
        data["history"] = {"pl_years": years, "quarters": quarters,
                           "short": years < THIN_YEARS and quarters < THIN_QUARTERS}
        return data

    def _company_page(self, symbol: str, view: str = "auto", name: str = "") -> tuple[str, Page, dict]:
        sym = self._norm(symbol)
        slugs: list[str] = []
        alias = self._aliases().get(sym)
        if alias:
            slugs.append(alias)
        if _SYMBOL.match(sym):
            slugs.append(sym)
        if self._codes.get(sym):
            slugs.append(self._codes[sym])
        last_err: Exception = NotFound("No Screener.in company matches '%s'." % symbol)
        for slug in dict.fromkeys(slugs):
            try:
                page, data = self._load(slug, view)
                self._remember(sym, slug)
                return slug, page, data
            except (NotFound, ParseError) as exc:
                last_err = exc
        slug = self._search_slug(sym, name)
        if slug and slug not in slugs:
            page, data = self._load(slug, view)
            self._remember(sym, slug)
            return slug, page, data
        raise last_err

    def _prov(self, page: Page, data: dict) -> dict:
        extra = {k: data.get(k) for k in ("view_note", "history", "history_fill") if data.get(k) is not None}
        return page.provenance(view=data.get("view"), units="₹ crore unless stated", **extra)

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
