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


def table(n):
    return {"periods": ["P%d" % i for i in range(n)], "rows": {"Sales": [1.0] * n}}


def fake_page(quarters, years, view):
    return {"name": "X", "view": view, "quarters": table(quarters), "profit_loss": table(years)}


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
