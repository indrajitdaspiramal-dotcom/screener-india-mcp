"""Deterministic analytics computed from a parsed company page.

Unlike tools that hand raw tables to the AI and ask it to "spot red flags",
every check here is a fixed, testable rule with the evidence attached, so the
same page always gives the same answer.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------- helpers
def _row(table: Optional[dict], *names: str) -> list:
    """First matching row (case-insensitive, prefix match) from a parsed table."""
    if not table:
        return []
    rows = table.get("rows") or {}
    low = {k.lower(): v for k, v in rows.items()}
    for n in names:
        n = n.lower()
        if n in low:
            return low[n]
        for k, v in low.items():
            if k.startswith(n):
                return v
    return []


def _last(vals: list, back: int = 0):
    clean = [v for v in vals if v is not None]
    if len(clean) <= back:
        return None
    return clean[-1 - back]


def _annual(table: Optional[dict], *names: str) -> list:
    """Annual series without a trailing TTM column."""
    vals = _row(table, *names)
    if table and table.get("periods") and vals and str(table["periods"][-1]).upper().startswith("TTM"):
        vals = vals[:-1]
    return vals


def cagr(first: Optional[float], last: Optional[float], years: float) -> Optional[float]:
    if first is None or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return round(((last / first) ** (1.0 / years) - 1.0) * 100.0, 1)


def pct_change(new: Optional[float], old: Optional[float]) -> Optional[float]:
    if new is None or old is None or old == 0:
        return None
    return round((new - old) / abs(old) * 100.0, 1)


def _only(table: Optional[dict], basis: str) -> Optional[dict]:
    """The columns of one basis ('consolidated' / 'standalone') from a back-filled table."""
    if not table or not table.get("basis"):
        return table
    keep = [i for i, b in enumerate(table["basis"]) if b == basis]
    dates = table.get("period_end_dates")
    return {"periods": [table["periods"][i] for i in keep],
            "period_end_dates": [dates[i] for i in keep] if dates else None,
            "rows": {k: [v[i] if i < len(v) else None for i in keep] for k, v in table["rows"].items()}}


def _consistent(company: dict) -> tuple[dict, Optional[str]]:
    """Multi-year checks must not compare a standalone year with a consolidated one. If the page was back-filled,
    use the consolidated columns when they hold at least 4 years, else the whole standalone page."""
    pl = company.get("profit_loss")
    if not pl or not pl.get("basis") or "standalone" not in pl["basis"]:
        return company, None
    cons = dict(company)
    for key in ("profit_loss", "balance_sheet", "cash_flow", "ratios_history"):
        cons[key] = _only(company.get(key), "consolidated")
    if len(_annual(cons.get("profit_loss"), "sales", "revenue", "net profit")) >= 4 or not company.get("_standalone"):
        return cons, "consolidated"
    return company["_standalone"], "standalone"


# ---------------------------------------------------------------- earnings trend
def earnings_trend(company: dict, quarters: int = 8) -> dict:
    """Quarterly sales/profit with YoY growth and whether growth is accelerating."""
    q = company.get("quarters")
    if not q:
        return {"quarters": [], "verdict": "no quarterly data"}
    periods = q["periods"]
    sales = _row(q, "sales", "revenue")
    op = _row(q, "operating profit", "financing profit")
    opm = _row(q, "opm %", "financing margin %")
    np_ = _row(q, "net profit")
    eps = _row(q, "eps in rs", "eps")
    basis = q.get("basis") or [None] * len(periods)
    out = []
    for i, p in enumerate(periods):
        def at(series, j=i):
            return series[j] if 0 <= j < len(series) else None
        same = i >= 4 and at(basis) == at(basis, i - 4)     # never YoY across standalone -> consolidated
        row = {
            "period": p,
            "sales_cr": at(sales),
            "operating_profit_cr": at(op),
            "opm_pct": at(opm),
            "net_profit_cr": at(np_),
            "eps": at(eps),
            "sales_yoy_pct": pct_change(at(sales), at(sales, i - 4)) if same else None,
            "profit_yoy_pct": pct_change(at(np_), at(np_, i - 4)) if same else None,
        }
        if at(basis):
            row["basis"] = at(basis)
        out.append(row)
    out = out[-quarters:]
    s_yoy = [r["sales_yoy_pct"] for r in out if r["sales_yoy_pct"] is not None]
    p_yoy = [r["profit_yoy_pct"] for r in out if r["profit_yoy_pct"] is not None]

    def trend(xs):
        if len(xs) < 4:
            return "insufficient history"
        recent, prior = sum(xs[-2:]) / 2, sum(xs[-4:-2]) / 2
        if recent > prior + 3:
            return "accelerating"
        if recent < prior - 3:
            return "decelerating"
        return "steady"

    return {"quarters": out, "sales_growth": trend(s_yoy), "profit_growth": trend(p_yoy),
            "method": "YoY vs same quarter last year; trend = average of last 2 YoY vs the 2 before (±3 pts)."}


# ---------------------------------------------------------------- red flags
def _flag(check, status, severity, evidence):
    return {"check": check, "status": status, "severity": severity if status == "flag" else None,
            "evidence": evidence}


def red_flags(company: dict) -> dict:
    company, basis = _consistent(company)
    pl, bs, cf, rh = (company.get(k) for k in ("profit_loss", "balance_sheet", "cash_flow", "ratios_history"))
    sh = (company.get("shareholding") or {}).get("quarterly")
    checks = []

    # 1. Cash conversion: 5-year operating cash flow vs net profit.
    cfo = [v for v in _annual(cf, "cash from operating activity")[-5:] if v is not None]
    pat = [v for v in _annual(pl, "net profit")[-5:] if v is not None]
    if len(cfo) >= 3 and len(pat) >= 3 and sum(pat) > 0:
        ratio = round(sum(cfo) / sum(pat), 2)
        st = "flag" if ratio < 0.7 else "ok"
        checks.append(_flag("Cash conversion (CFO / net profit, last %d years)" % min(len(cfo), len(pat)), st,
                            "high" if ratio < 0.4 else "medium", "CFO/PAT = %.2f" % ratio))
    else:
        checks.append(_flag("Cash conversion", "na", None, "not enough cash-flow history"))

    # 2-3. Working capital stretch.
    for label, key in (("Debtor days", "debtor days"), ("Inventory days", "inventory days")):
        series = [v for v in _row(rh, key) if v is not None]
        if len(series) >= 4:
            now, before = series[-1], series[-4]
            st = "flag" if before and now > 90 and now > before * 1.3 else "ok"
            checks.append(_flag("%s rising" % label, st, "medium", "%s: %s three years ago → %s now" % (label, before, now)))
        else:
            checks.append(_flag("%s rising" % label, "na", None, "not reported"))

    # Banks/NBFCs: fees and treasury income are core business, and leverage is the model.
    is_lender = bool(_row(bs, "deposits")) or bool(_row(pl, "financing profit"))

    # 4. Other income propping profit (not meaningful for lenders).
    oi, pbt = _last(_annual(pl, "other income")), _last(_annual(pl, "profit before tax"))
    if oi is not None and pbt and pbt > 0 and not is_lender:
        share = round(oi / pbt * 100, 1)
        checks.append(_flag("Other income share of profit before tax", "flag" if share > 25 else "ok",
                            "medium", "%.1f%% of PBT" % share))

    # 5. Leverage.
    borrow = _last(_annual(bs, "borrowings", "borrowing"))
    equity = (_last(_annual(bs, "equity capital")) or 0) + (_last(_annual(bs, "reserves")) or 0)
    if borrow is not None and equity > 0 and not is_lender:
        de = round(borrow / equity, 2)
        checks.append(_flag("Debt to equity", "flag" if de > 1.0 else "ok", "high" if de > 2 else "medium",
                            "borrowings ₹%s cr / net worth ₹%s cr = %.2f" % (borrow, round(equity), de)))

    # 6. Debt growing faster than sales (3 years).
    b_series = [v for v in _annual(bs, "borrowings", "borrowing") if v is not None]
    s_series = [v for v in _annual(pl, "sales", "revenue") if v is not None]
    if len(b_series) >= 4 and len(s_series) >= 4 and not is_lender:
        bg, sg = cagr(b_series[-4], b_series[-1], 3), cagr(s_series[-4], s_series[-1], 3)
        if bg is not None and sg is not None:
            st = "flag" if bg > sg + 10 and b_series[-1] > 0.25 * max(equity, 1) else "ok"
            checks.append(_flag("Debt growing faster than sales (3y)", st, "medium",
                                "borrowings %+.1f%%/yr vs sales %+.1f%%/yr" % (bg, sg)))

    # 7. Profit lagging sales (3y).
    p_series = [v for v in _annual(pl, "net profit") if v is not None]
    if len(p_series) >= 4 and len(s_series) >= 4:
        sg, pg = cagr(s_series[-4], s_series[-1], 3), cagr(p_series[-4], p_series[-1], 3)
        if sg is not None and pg is not None:
            st = "flag" if sg > 10 and pg < sg / 2 else "ok"
            checks.append(_flag("Profit growth lagging sales growth (3y)", st, "medium",
                                "sales %+.1f%%/yr vs profit %+.1f%%/yr" % (sg, pg)))

    # 8. Returns on capital falling three years running.
    roce = [v for v in _row(rh, "roce %", "roe %") if v is not None]
    if len(roce) >= 4:
        falling = roce[-1] < roce[-2] < roce[-3] < roce[-4]
        checks.append(_flag("Return on capital falling 3 years in a row", "flag" if falling else "ok", "medium",
                            "last four years: %s" % ", ".join("%g" % x for x in roce[-4:])))

    # 9. Promoter holding falling.
    prom = [v for v in _row(sh, "promoters") if v is not None]
    if len(prom) >= 5:
        drop = round(prom[-5] - prom[-1], 2)
        checks.append(_flag("Promoter holding falling (4 quarters)", "flag" if drop > 2 else "ok",
                            "high" if drop > 5 else "medium", "%.2f%% → %.2f%%" % (prom[-5], prom[-1])))

    # 10. Low tax rate on a profitable company.
    tax = _last(_annual(pl, "tax %"))
    if tax is not None and pbt and pbt > 0:
        checks.append(_flag("Unusually low tax rate", "flag" if tax < 15 else "ok", "low", "tax rate %g%%" % tax))

    # 11. Capital work in progress ballooning.
    cwip, fa = _last(_annual(bs, "cwip")), _last(_annual(bs, "fixed assets"))
    if cwip is not None and fa:
        share = round(cwip / fa * 100, 1)
        checks.append(_flag("Capital work-in-progress vs fixed assets", "flag" if share > 50 else "ok", "low",
                            "CWIP is %.1f%% of fixed assets" % share))

    # 12. Equity dilution.
    eq = [v for v in _annual(bs, "equity capital") if v is not None]
    if len(eq) >= 4 and eq[-4]:
        growth = round((eq[-1] / eq[-4] - 1) * 100, 1)
        checks.append(_flag("Share capital increase (3y, possible dilution or bonus)", "flag" if growth > 10 else "ok",
                            "low", "equity capital %+.1f%% (a bonus issue or split also raises this)" % growth))

    flagged = [c for c in checks if c["status"] == "flag"]
    order = {"high": 0, "medium": 1, "low": 2}
    flagged.sort(key=lambda c: order.get(c["severity"] or "low", 3))
    out = {
        "summary": "%d of %d checks flagged" % (len(flagged), sum(1 for c in checks if c["status"] != "na")),
        "flags": flagged,
        "checks": checks,
        "lender_rules": is_lender,
        "not_covered": ["auditor remarks", "related-party transactions", "pledged shares", "contingent liabilities"]
        + (["asset quality (GNPA/NNPA trend)", "capital adequacy"] if is_lender else []),
        "note": "Screening rules on reported numbers, not a forensic audit. Read the annual report before acting.",
    }
    if basis:
        out["basis"] = basis
        out["basis_note"] = ("checks use %s figures only, so no comparison crosses standalone and consolidated "
                             "years" % basis)
    return out


# ---------------------------------------------------------------- compare
def comparison_row(symbol: str, company: dict) -> dict:
    r = company.get("ratios") or {}
    g = company.get("growth") or {}
    pl = company.get("profit_loss")
    opm = _last(_annual(pl, "opm %"))
    return {
        "symbol": symbol,
        "name": company.get("name"),
        "industry": (company.get("classification") or {}).get("industry"),
        "market_cap_cr": r.get("market_cap_cr"),
        "price": r.get("current_price"),
        "pe": r.get("pe"),
        "price_to_book": round(r["current_price"] / r["book_value"], 2) if r.get("current_price") and r.get("book_value") else None,
        "roce_pct": r.get("roce_pct"),
        "roe_pct": r.get("roe_pct"),
        "opm_pct_last_year": opm,
        "dividend_yield_pct": r.get("dividend_yield_pct"),
        "sales_cagr_3y_pct": (g.get("compounded_sales_growth") or {}).get("3y"),
        "sales_cagr_5y_pct": (g.get("compounded_sales_growth") or {}).get("5y"),
        "profit_cagr_3y_pct": (g.get("compounded_profit_growth") or {}).get("3y"),
        "profit_cagr_5y_pct": (g.get("compounded_profit_growth") or {}).get("5y"),
    }
