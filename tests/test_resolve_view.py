"""0.1.1: BSE-code fallback, Screener-search fallback (unambiguous only), remembered aliases, and choosing
the richer of a thin consolidated page vs the standalone page. Born from a 91-holding live test (25-Oct-2026):
13 BSE-only/SME companies were 'not found' by ticker, and SG Finserve's consolidated page had 1 quarter."""
import json

import httpx
import pytest

from screener_india_mcp import parsers
from screener_india_mcp.errors import NotFound
from screener_india_mcp.service import Screener
from test_governor_client import make


MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def table(n, step, end, value):
    """n dated columns ending at `end` (year, month), `step` months apart, every value = `value`."""
    y, m = end
    labels = []
    for _ in range(n):
        labels.append("%s %d" % (MON[m - 1], y))
        m -= step
        while m < 1:
            m += 12
            y -= 1
    labels.reverse()
    return {"periods": labels, "period_end_dates": None,
            "rows": {"Sales": [value] * n, "Net Profit": [value] * n}}


def fake_page(quarters, years, view):
    v = 2.0 if view == "consolidated" else 1.0       # tell the two pages' numbers apart
    return {"name": "X", "view": view, "quarters": table(quarters, 3, (2026, 9), v) if quarters else None,
            "profit_loss": table(years, 12, (2026, 3), v) if years else None}


@pytest.fixture
def pages(monkeypatch):
    """Map of URL path -> (quarters, P&L years). Unknown paths answer 404."""
    spec: dict = {}

    def parse(html):
        q, y, v = json.loads(html.split("<!--", 1)[1].split("-->", 1)[0])
        return fake_page(q, y, v)

    monkeypatch.setattr(parsers, "parse_company_page", parse)

    def handler(req):
        path = req.url.path
        if path.startswith("/api/company/search/"):
            return httpx.Response(200, json=spec.get("__search__", []))
        if path in spec:
            q, y = spec[path]
            v = "consolidated" if path.endswith("/consolidated/") else "standalone"
            return httpx.Response(200, text='<div id="top-ratios"></div><!--%s-->' % json.dumps([q, y, v]))
        return httpx.Response(404, text="nope")

    return spec, handler


def test_rich_consolidated_is_kept_with_one_request(tmp_path, pages):
    spec, h = pages
    spec["/company/RICH/consolidated/"] = (13, 12)
    spec["/company/RICH/"] = (13, 12)
    c, calls, _ = make(tmp_path, h)
    sym, page, d = Screener(c)._company_page("RICH")
    assert d["view"] == "consolidated" and len(calls) == 1
    assert d["history"] == {"pl_years": 12, "quarters": 13, "short": False}


def test_thin_consolidated_loses_to_standalone(tmp_path, pages):
    spec, h = pages
    spec["/company/SGFIN/consolidated/"] = (1, 0)
    spec["/company/SGFIN/"] = (13, 10)
    c, calls, _ = make(tmp_path, h)
    _, _, d = Screener(c)._company_page("SGFIN")
    assert d["view"] == "standalone" and "only 1 quarters" in d["view_note"]
    assert len(calls) == 2


def test_thin_consolidated_keeps_latest_and_fills_history_from_standalone(tmp_path, pages):
    """Option B: the latest numbers stay consolidated (subsidiaries included); older columns come from the
    standalone page, labelled, and no YoY or multi-year check crosses the join."""
    from screener_india_mcp import analytics
    spec, h = pages
    spec["/company/KREONFIN/consolidated/"] = (6, 3)
    spec["/company/KREONFIN/"] = (13, 10)
    c, calls, _ = make(tmp_path, h)
    _, page, d = Screener(c)._company_page("KREONFIN")
    assert d["view"] == "consolidated" and page.url.endswith("/consolidated/") and len(calls) == 2
    q, pl = d["quarters"], d["profit_loss"]
    assert len(q["periods"]) == 13 and q["basis"] == ["standalone"] * 7 + ["consolidated"] * 6
    assert q["rows"]["Sales"][:7] == [1.0] * 7 and q["rows"]["Sales"][7:] == [2.0] * 6
    assert q["periods"][6] == "Mar 2025" and q["periods"][7] == "Jun 2025"    # contiguous, no overlap
    assert len(pl["periods"]) == 10 and pl["basis"].count("consolidated") == 3
    assert d["history_fill"]["columns_added"] == {"quarters": 7, "profit_loss": 7}
    assert d["history"]["short"] is False and "consolidated" in d["view_note"]
    tr = analytics.earnings_trend(d, 13)["quarters"]
    assert [r["sales_yoy_pct"] for r in tr][7:11] == [None] * 4        # consolidated vs standalone: no YoY
    assert tr[11]["sales_yoy_pct"] == 0.0                               # consolidated vs consolidated: fine
    rf = analytics.red_flags(d)
    assert rf["basis"] == "standalone"            # only 3 consolidated years -> whole standalone page
    prov = Screener(c)._prov(page, d)
    assert prov["history_fill"]["from"] == "standalone" and "_standalone" not in prov


def test_too_new_consolidated_uses_standalone_as_primary(tmp_path, pages):
    spec, h = pages
    spec["/company/NEWSUB/consolidated/"] = (3, 4)      # < 4 quarters: no trailing-12-month P/E
    spec["/company/NEWSUB/"] = (13, 10)
    c, _, _ = make(tmp_path, h)
    _, page, d = Screener(c)._company_page("NEWSUB")
    assert d["view"] == "standalone" and "trailing-12-month" in d["view_note"] and "basis" not in d["quarters"]


def test_backfill_uses_date_keys_and_skips_ttm():
    from screener_india_mcp.service import _backfill
    cons = {"periods": ["Mar 2025", "Mar 2026", "TTM"], "period_end_dates": ["2025-03-31", "2026-03-31", None],
            "rows": {"Sales": [5.0, 6.0, 7.0], "Only Cons": [1.0, 1.0, 1.0]}}
    stand = {"periods": ["Mar 2023", "Mar 2024", "Mar 2025", "TTM"], "period_end_dates": None,
             "rows": {"sales": [1.0, 2.0, 3.0, 4.0]}}
    t, n = _backfill(cons, stand)
    assert n == 2 and t["periods"] == ["Mar 2023", "Mar 2024", "Mar 2025", "Mar 2026", "TTM"]
    assert t["rows"]["Sales"] == [1.0, 2.0, 5.0, 6.0, 7.0] and t["rows"]["Only Cons"][:2] == [None, None]
    assert t["basis"] == ["standalone", "standalone", "consolidated", "consolidated", "consolidated"]


def test_thin_consolidated_kept_when_standalone_is_thinner(tmp_path, pages):
    spec, h = pages
    spec["/company/NEWCO/consolidated/"] = (5, 2)
    spec["/company/NEWCO/"] = (4, 2)
    c, _, _ = make(tmp_path, h)
    _, _, d = Screener(c)._company_page("NEWCO")
    assert d["view"] == "consolidated" and d["history"]["short"] is True


def test_bse_code_fallback_and_alias_remembered(tmp_path, pages):
    spec, h = pages
    spec["/company/530215/consolidated/"] = (12, 10)
    c, calls, _ = make(tmp_path, h)
    s = Screener(c)
    s.set_bse_codes({"KINGSINFR": "530215", "BAD": "not-a-code"})
    slug, _, _ = s._company_page("KINGSINFR")
    assert slug == "530215" and "BAD" not in s._codes
    n = len(calls)
    s2 = Screener(c)                                   # a fresh instance reads the remembered alias
    slug2, page, _ = s2._company_page("KINGSINFR")
    assert slug2 == "530215" and page.from_cache and len(calls) == n


def test_search_fallback_exact_match_only(tmp_path, pages):
    spec, h = pages
    spec["/company/544467/consolidated/"] = (4, 3)
    spec["__search__"] = [{"name": "National Securities Depository", "url": "/company/544467/", "id": 1},
                          {"name": "NSDL Bank", "url": "/company/OTHER/", "id": 2}]
    c, _, _ = make(tmp_path, h)
    s = Screener(c)
    s.set_bse_codes({"NSDL": "544467"})
    spec.pop("/company/544467/consolidated/")          # code page missing too -> search must find it
    spec["/company/544467/"] = (4, 3)
    slug, _, d = s._company_page("NSDL")
    assert slug == "544467" and d["view"] == "standalone"


def test_ambiguous_search_is_refused(tmp_path, pages):
    spec, h = pages
    spec["__search__"] = [{"name": "Valiant Organics", "url": "/company/VALIANTORG/", "id": 1},
                          {"name": "Valiant Laboratories", "url": "/company/VALIANTLAB/", "id": 2}]
    spec["/company/VALIANTORG/consolidated/"] = (13, 12)
    c, _, _ = make(tmp_path, h)
    with pytest.raises(NotFound):
        Screener(c)._company_page("VALIANT")          # never guess between two different companies
