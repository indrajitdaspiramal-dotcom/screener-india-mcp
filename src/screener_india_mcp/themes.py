"""Ready-made screens written in Screener.in's query language.

They are starting points for research, not recommendations.
"""

THEMES = {
    "quality_compounders": (
        "Consistent growth with high returns",
        "Sales growth 5Years > 12 AND Profit growth 5Years > 15 AND "
        "Average return on capital employed 5Years > 18 AND Debt to equity < 0.5",
    ),
    "quality_at_reasonable_price": (
        "High returns at a moderate valuation",
        "Return on capital employed > 18 AND Price to Earning < 25 AND "
        "Profit growth 3Years > 12 AND Debt to equity < 0.5 AND Market Capitalization > 1000",
    ),
    "high_roce_low_debt": (
        "Capital-efficient, lightly indebted businesses",
        "Return on capital employed > 22 AND Debt to equity < 0.2 AND Market Capitalization > 500",
    ),
    "earnings_acceleration": (
        "Latest quarter profit growth well above the 3-year trend",
        "YOY Quarterly profit growth > 30 AND YOY Quarterly sales growth > 15 AND "
        "Profit growth 3Years > 10 AND Market Capitalization > 500",
    ),
    "margin_expansion": (
        "Operating margin above its own 5-year average",
        "OPM > OPM 5Year + 3 AND Sales growth 3Years > 10 AND Market Capitalization > 500",
    ),
    "turnaround": (
        "Recent profit recovery after a weak stretch",
        "Profit growth 3Years < 0 AND YOY Quarterly profit growth > 50 AND Net profit > 0",
    ),
    "cash_rich_cheap": (
        "Low valuation with cash generation",
        "Price to Earning < 15 AND Free cash flow 3years > 0 AND Debt to equity < 0.3 AND Market Capitalization > 300",
    ),
    "dividend_payers": (
        "Steady dividend payers with sound finances",
        "Dividend yield > 2 AND Average return on equity 5Years > 12 AND Debt to equity < 0.5",
    ),
    "small_cap_growth": (
        "Smaller companies growing fast with good returns",
        "Market Capitalization > 300 AND Market Capitalization < 5000 AND Sales growth 3Years > 20 AND "
        "Profit growth 3Years > 20 AND Return on capital employed > 15",
    ),
    "promoter_buying": (
        "Promoters increasing their stake",
        "Change in promoter holding > 1 AND Pledged percentage < 5 AND Market Capitalization > 300",
    ),
    "low_pledge_high_promoter": (
        "High promoter holding without pledges",
        "Promoter holding > 60 AND Pledged percentage = 0 AND Return on capital employed > 15",
    ),
    "lenders_quality": (
        "Banks/NBFCs with healthy returns and low bad loans",
        "Return on equity > 15 AND Net NPA < 1.5 AND Profit growth 3Years > 15",
    ),
}


def list_themes() -> list[dict]:
    return [{"theme": k, "description": d, "query": q} for k, (d, q) in THEMES.items()]


def match_theme(name: str) -> str | None:
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    if key in THEMES:
        return key
    for k in THEMES:
        if key in k or k in key:
            return k
    return None
