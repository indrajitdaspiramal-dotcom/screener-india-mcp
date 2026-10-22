from conftest import fixture_text

from screener_india_mcp import parsers


def company():
    return parsers.parse_company_page(fixture_text("company_example.html"))


def test_identity_and_ratios():
    c = company()
    assert c["name"] == "Example Industries Ltd"
    assert c["nse_symbol"] == "EXAMPLE" and c["bse_code"] == "999001"
    assert c["company_id"] == "9001" and c["warehouse_id"] == "7001"
    assert c["view"] == "consolidated"
    assert c["website"] == "http://www.example.org"
    r = c["ratios"]
    assert r["market_cap_cr"] == 5000 and r["current_price"] == 1000
    assert r["high_52w"] == 1200 and r["low_52w"] == 800
    assert r["pe"] == 73.5 and r["roce_pct"] == 24.0 and r["face_value"] == 2.0
    assert "[1]" not in c["about"]


def test_classification_pros_cons_benchmarks():
    c = company()
    assert c["classification"] == {"broad_sector": "Industrials", "sector": "Capital Goods",
                                   "broad_industry": "Electrical Equipment", "industry": "Widgets"}
    assert c["pros"] == ["Company is almost debt free."]
    assert c["cons"][0].startswith("Stock is trading")
    assert c["benchmarks"] == ["BSE 500", "Nifty 500"]


def test_tables():
    c = company()
    q = c["quarters"]
    assert q["periods"][0] == "Jun 2024" and q["period_end_dates"][-1] == "2026-06-30"
    assert q["rows"]["Sales"][-1] == 150                       # '+' button text stripped from label
    assert q["rows"]["OPM %"][0] == 20
    pl = c["profit_loss"]
    assert pl["periods"][-1] == "TTM" and pl["rows"]["Tax %"][-1] is None
    assert c["growth"]["compounded_sales_growth"] == {"10y": 18, "5y": 15, "3y": 14, "ttm": 22}
    assert c["balance_sheet"]["rows"]["Borrowings"][-1] == 8
    assert c["cash_flow"]["rows"]["Cash from Operating Activity"][0] == 28
    assert c["ratios_history"]["rows"]["Debtor Days"][-1] == 98


def test_shareholding_and_documents():
    c = company()
    sh = c["shareholding"]["quarterly"]
    assert sh["rows"]["Promoters"][-1] == 56.5
    assert sh["rows"]["No. of Shareholders"][-1] == 60000
    assert c["shareholding"]["yearly"]["rows"]["Promoters"] == [59.5, 58.0]
    d = c["documents"]
    assert d["announcements"][0]["title"] == "Board Meeting Outcome"
    assert d["announcements"][0]["date"].startswith("2026-10-07")
    assert d["announcements"][0]["summary"] == "Board approved quarterly results."
    assert d["announcements"][1]["summary"] is None
    assert [a["year"] for a in d["annual_reports"]] == [2026, 2025]
    assert d["credit_ratings"][0]["url"].endswith("cr1.html")
    cc = d["concalls"][0]
    assert cc["period"] == "Aug 2026" and cc["transcript"].endswith("t.pdf")
    assert cc["presentation"].endswith("p.pdf") and cc["recording"].endswith("r.mp3")


def test_search_chart_peers_screen():
    s = parsers.parse_search(fixture_text("search_example.json"))
    assert s[0]["symbol"] == "EXAMPLE" and s[1]["symbol"] == "EXBANK"
    ch = parsers.parse_chart(fixture_text("chart_example.json"))
    assert ch["Price"][-1] == ["2026-10-21", 1000.0]
    assert ch["Volume"][-1] == ["2026-10-21", 15000.0, 60.0]
    p = parsers.parse_peers(fixture_text("peers_example.html"))
    assert [x["symbol"] for x in p["peers"]] == ["BIGCO", "EXAMPLE"]
    assert p["peers"][0]["CMP Rs."] == 2500.0
    assert p["median"] is not None
    sc = parsers.parse_screen_results(fixture_text("screen_example.html"))
    assert sc["count"] == 37
    assert [x["symbol"] for x in sc["companies"]] == ["AAA", "BBB"]
    assert sc["companies"][1]["CMP Rs."] == 1450.0


def test_missing_sections_do_not_crash():
    c = parsers.parse_company_page("<html><body><h1>Nothing</h1></body></html>")
    assert c["quarters"] is None and c["ratios"] == {} and c["documents"]["announcements"] == []
    assert parsers.page_has_company_data("<html></html>") is False


def test_num():
    assert parsers.num("1,234.5") == 1234.5
    assert parsers.num(" -12% ") == -12.0
    assert parsers.num("") is None and parsers.num(None) is None
    assert parsers.num("₹ 2,249") == 2249.0


def test_real_page_quirks():
    c = company()
    assert "Raw PDF" not in c["quarters"]["rows"]                 # link-only rows are dropped
    assert "CFO/EBITDA" in c["cash_flow"]["rows"]                 # tooltip text stripped from the label
    p = parsers.parse_peers(fixture_text("peers_example.html"))
    assert p["peers"][0]["S.No."] == 1.0
    assert "Company" not in p["median"] and p["median"]["companies_in_median"] == 2
