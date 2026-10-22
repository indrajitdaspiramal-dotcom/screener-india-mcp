from conftest import fixture_text

from screener_india_mcp import analytics, parsers


def company():
    return parsers.parse_company_page(fixture_text("company_example.html"))


def test_earnings_trend():
    t = analytics.earnings_trend(company(), quarters=8)
    assert len(t["quarters"]) == 8
    last = t["quarters"][-1]
    assert last["period"] == "Jun 2026"
    assert last["sales_yoy_pct"] == round((150 - 110) / 110 * 100, 1)
    assert last["profit_yoy_pct"] == round((19 - 11) / 11 * 100, 1)
    assert t["sales_growth"] == "accelerating" and t["profit_growth"] == "accelerating"


def test_red_flags_deterministic():
    r1 = analytics.red_flags(company())
    r2 = analytics.red_flags(company())
    assert r1 == r2
    by = {c["check"].split(" (")[0]: c for c in r1["checks"]}
    # promoter holding 60 -> 56.5 over 4 quarters = 3.5 pts drop -> flag
    assert by["Promoter holding falling"]["status"] == "flag"
    # debtor days 70 three years ago -> 98 now (>90 and >1.3x) -> flag
    assert by["Debtor days rising"]["status"] == "flag"
    # cash conversion: CFO 245 / PAT 264.5 over 6 yrs (last 5 used) -> ok
    assert by["Cash conversion"]["status"] == "ok"
    assert by["Debt to equity"]["status"] == "ok"
    assert by["Return on capital falling 3 years in a row"]["status"] == "flag"   # 27,26,25,24
    assert r1["flags"][0]["severity"] in ("high", "medium")


def test_cagr_and_compare_row():
    assert analytics.cagr(100, 200, 5) == 14.9
    assert analytics.cagr(0, 200, 5) is None
    row = analytics.comparison_row("EXAMPLE", company())
    assert row["price_to_book"] == round(1000 / 365, 2)
    assert row["sales_cagr_3y_pct"] == 14 and row["industry"] == "Widgets"
