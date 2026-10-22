"""Parsers for Screener.in pages.

Written to survive small layout changes: tables are found by section id and by
content, not by brittle CSS paths, and every parser returns ``None``/empty for
a missing piece instead of crashing.
"""

from __future__ import annotations

import html as _html
import json
import re
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


# ---------------------------------------------------------------- primitives
def clean(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", _html.unescape(text or "")).replace("\xa0", " ").strip()


def num(text: Any) -> Optional[float]:
    """'1,234.5' → 1234.5 · '35%' → 35.0 · '-12' → -12.0 · '' / '--' → None."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = clean(str(text)).replace(",", "").replace("₹", "").replace("%", "")
    m = _NUM.search(s)
    return float(m.group(0)) if m else None


def snake(label: str) -> str:
    s = clean(label).lower().replace("%", " pct").replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _row_label(td: Tag) -> str:
    for tip in td.select(".tooltip, [role=tooltip]"):     # explanatory pop-ups are not part of the label
        tip.decompose()
    return clean(td.get_text(" ")).rstrip("+").strip()


# ---------------------------------------------------------------- tables
def parse_data_table(section: Optional[Tag]) -> Optional[dict]:
    """A Screener 'data-table' → {periods, period_end_dates, rows: {label: [float|None]}}."""
    if section is None:
        return None
    table = section.select_one("table.data-table") or section.find("table")
    if table is None:
        return None
    head = table.find("thead")
    ths = head.find_all("th") if head else []
    if not ths:
        first = table.find("tr")
        ths = first.find_all(["th", "td"]) if first else []
    periods = [clean(th.get_text()) for th in ths[1:]]
    dates = [th.get("data-date-key") for th in ths[1:]]
    rows: dict[str, list] = {}
    body = table.find("tbody") or table
    for tr in body.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        label = _row_label(tds[0])
        if not label:
            continue
        vals = [num(td.get_text()) for td in tds[1:]]
        if all(v is None for v in vals):        # link-only rows such as "Raw PDF"
            continue
        rows[label] = vals
    if not rows:
        return None
    return {"periods": periods, "period_end_dates": dates if any(dates) else None, "rows": rows}


def parse_ranges(section: Optional[Tag]) -> dict:
    """'Compounded Sales Growth' etc. → {compounded_sales_growth: {'10y': 25.0, ...}}."""
    out: dict[str, dict] = {}
    if section is None:
        return out
    for t in section.select("table.ranges-table"):
        th = t.find("th")
        if not th:
            continue
        name = snake(th.get_text())
        vals = {}
        for tr in t.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) == 2:
                k = clean(tds[0].get_text()).rstrip(":").lower()
                k = {"10 years": "10y", "5 years": "5y", "3 years": "3y", "ttm": "ttm",
                     "1 year": "1y", "last year": "last_year"}.get(k, snake(k))
                vals[k] = num(tds[1].get_text())
        out[name] = vals
    return out


# ---------------------------------------------------------------- company page
_RATIO_KEYS = {
    "market cap": "market_cap_cr",
    "current price": "current_price",
    "stock p/e": "pe",
    "book value": "book_value",
    "dividend yield": "dividend_yield_pct",
    "roce": "roce_pct",
    "roe": "roe_pct",
    "face value": "face_value",
}


def _top_ratios(soup: BeautifulSoup) -> dict:
    out: dict[str, Any] = {}
    for li in soup.select("#top-ratios li"):
        name_el = li.select_one(".name")
        if not name_el:
            continue
        name = clean(name_el.get_text()).lower()
        nums = [num(n.get_text()) for n in li.select(".number")]
        if name == "high / low":
            out["high_52w"] = nums[0] if nums else None
            out["low_52w"] = nums[1] if len(nums) > 1 else None
            continue
        key = _RATIO_KEYS.get(name, snake(name))
        out[key] = nums[0] if nums else num(li.select_one(".value").get_text() if li.select_one(".value") else "")
    return out


def _classification(soup: BeautifulSoup) -> dict:
    out = {}
    for a in soup.select('#peers a[href^="/market/"]'):
        title = (a.get("title") or "").strip().lower()
        key = {"broad sector": "broad_sector", "sector": "sector", "broad industry": "broad_industry",
               "industry": "industry"}.get(title)
        if key:
            out[key] = clean(a.get_text())
    return out


def _documents(soup: BeautifulSoup) -> dict:
    docs: dict[str, list] = {"announcements": [], "annual_reports": [], "credit_ratings": [], "concalls": []}
    sec = soup.select_one("section#documents")
    if sec is None:
        return docs
    for li in sec.select("#company-announcements-tab ul.list-links li"):
        a = li.find("a")
        if not a:
            continue
        t = li.find("time")
        sub = a.select_one("div.smaller")
        summary = None
        if sub is not None:
            txt = clean(sub.get_text(" "))
            summary = txt.split(" - ", 1)[1] if " - " in txt else None
        title = clean("".join(x if isinstance(x, str) else "" for x in a.contents)) or clean(a.get_text(" "))
        docs["announcements"].append({
            "title": title,
            "date": t.get("datetime") if t else None,
            "summary": summary,
            "url": a.get("href"),
        })
    for block in sec.select("div.documents"):
        classes = block.get("class") or []
        h = block.find("h3")
        heading = clean(h.get_text()).lower() if h else ""
        if "annual-reports" in classes or heading.startswith("annual report"):
            for li in block.select("ul.list-links li"):
                a = li.find("a")
                if a:
                    title = clean(a.get_text())
                    m = re.search(r"(19|20)\d\d", title)
                    docs["annual_reports"].append({"title": title, "year": int(m.group(0)) if m else None,
                                                   "url": a.get("href")})
        elif "credit-ratings" in classes or heading.startswith("credit rating"):
            for li in block.select("ul.list-links li"):
                a = li.find("a")
                if a:
                    sub = a.select_one("div.smaller")
                    docs["credit_ratings"].append({
                        "title": clean("".join(x if isinstance(x, str) else "" for x in a.contents)) or clean(a.get_text()),
                        "detail": clean(sub.get_text(" ")) if sub else None,
                        "url": a.get("href"),
                    })
        elif "concalls" in classes or heading.startswith("concall"):
            for li in block.select("ul.list-links li"):
                period_el = li.find("div")
                item = {"period": clean(period_el.get_text()) if period_el else None,
                        "transcript": None, "presentation": None, "recording": None, "notes": None}
                for a in li.find_all("a"):
                    lab = clean(a.get_text()).lower()
                    href = a.get("href")
                    if lab.startswith("transcript"):
                        item["transcript"] = href
                    elif lab in ("ppt", "presentation"):
                        item["presentation"] = href
                    elif lab in ("rec", "recording", "audio"):
                        item["recording"] = href
                    elif "notes" in lab:
                        item["notes"] = href
                docs["concalls"].append(item)
    return docs


def _shareholding(soup: BeautifulSoup) -> dict:
    sec = soup.select_one("section#shareholding")
    if sec is None:
        return {}
    return {
        "quarterly": parse_data_table(sec.select_one("#quarterly-shp")),
        "yearly": parse_data_table(sec.select_one("#yearly-shp")),
    }


def _list_items(el: Optional[Tag]) -> list[str]:
    return [clean(li.get_text(" ")) for li in el.find_all("li")] if el else []


def parse_company_page(html: str) -> dict:
    soup = _soup(html)
    info = soup.select_one("#company-info")
    h1 = soup.select_one("#top h1") or soup.find("h1")
    name = clean(h1.get_text(" ")) if h1 else None
    bse = nse = website = None
    for a in soup.select("#top a[href]"):
        txt = clean(a.get_text(" "))
        href = a.get("href", "")
        if txt.upper().startswith("BSE:") and bse is None:
            bse = clean(txt.split(":", 1)[1])
        elif txt.upper().startswith("NSE:") and nse is None:
            nse = clean(txt.split(":", 1)[1])
        elif website is None and href.startswith("http") and "bseindia" not in href and "nseindia" not in href \
                and "screener.in" not in href:
            website = href
    about_el = soup.select_one("#top .about")
    sections = {sid: soup.select_one("section#%s" % sid) for sid in
                ("quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios", "analysis")}
    consolidated = None
    if info is not None and info.get("data-consolidated") is not None:
        consolidated = info.get("data-consolidated") == "true"
    return {
        "name": name,
        "company_id": info.get("data-company-id") if info else None,
        "warehouse_id": info.get("data-warehouse-id") if info else None,
        "view": None if consolidated is None else ("consolidated" if consolidated else "standalone"),
        "nse_symbol": nse,
        "bse_code": bse,
        "website": website,
        "about": clean(about_el.get_text(" ")).replace(" [1]", "") if about_el else None,
        "ratios": _top_ratios(soup),
        "classification": _classification(soup),
        "pros": _list_items(sections["analysis"].select_one(".pros") if sections["analysis"] else None),
        "cons": _list_items(sections["analysis"].select_one(".cons") if sections["analysis"] else None),
        "quarters": parse_data_table(sections["quarters"]),
        "profit_loss": parse_data_table(sections["profit-loss"]),
        "growth": parse_ranges(sections["profit-loss"]),
        "balance_sheet": parse_data_table(sections["balance-sheet"]),
        "cash_flow": parse_data_table(sections["cash-flow"]),
        "ratios_history": parse_data_table(sections["ratios"]),
        "shareholding": _shareholding(soup),
        "documents": _documents(soup),
        "benchmarks": [clean(a.get_text()) for a in soup.select("#benchmarks a.tag")],
    }


def page_has_company_data(html: str) -> bool:
    return 'id="top-ratios"' in html


# ---------------------------------------------------------------- other endpoints
def parse_search(payload: Any) -> list[dict]:
    if isinstance(payload, (bytes, str)):
        payload = json.loads(payload)
    out = []
    for item in payload or []:
        url = item.get("url") or ""
        parts = [p for p in url.strip("/").split("/") if p]
        sym = parts[1] if len(parts) >= 2 and parts[0] == "company" else None
        out.append({"name": item.get("name"), "symbol": sym, "screener_id": item.get("id"), "url": url})
    return out


def parse_chart(payload: Any) -> dict:
    if isinstance(payload, (bytes, str)):
        payload = json.loads(payload)
    series: dict[str, list] = {}
    for ds in (payload or {}).get("datasets", []):
        metric = ds.get("metric") or ds.get("label") or "value"
        pts = []
        for p in ds.get("values", []):
            if not p:
                continue
            val = num(p[1]) if len(p) > 1 else None
            extra = p[2] if len(p) > 2 and isinstance(p[2], dict) else None
            if extra and "delivery" in extra:      # volume points carry {"delivery": pct}
                pts.append([p[0], val, num(extra.get("delivery"))])
            else:
                pts.append([p[0], val])
        series[metric] = pts
    return series


def _table_records(table: Tag) -> tuple[list[str], list[dict]]:
    rows = table.find_all("tr")
    headers: list[str] = []
    records = []
    for tr in rows:
        ths = tr.find_all("th")
        if ths and not tr.find("td"):
            headers = [clean(th.get_text(" ")) for th in ths]
            continue
        if not tr.select('a[href*="/company/"]'):
            continue
        cells = tr.find_all(["td", "th"])
        rec: dict[str, Any] = {}
        for i, cell in enumerate(cells):
            h = headers[i] if i < len(headers) else "col%d" % i
            a = cell.find("a", href=re.compile("/company/"))
            if a:
                rec["name"] = clean(a.get_text())
                href = a.get("href", "")
                parts = [p for p in href.strip("/").split("/") if p]
                rec["symbol"] = parts[1] if len(parts) >= 2 else None
                rec["url"] = href
            else:
                txt = clean(cell.get_text())
                rec[h] = num(txt) if _NUM.fullmatch(txt.replace(",", "").rstrip(".")) else txt
        records.append(rec)
    return headers, records


def parse_peers(html: str) -> dict:
    soup = _soup(html)
    table = soup.select_one("table.data-table") or soup.find("table")
    if table is None:
        return {"columns": [], "peers": [], "median": None}
    headers, recs = _table_records(table)
    median = None
    for tr in table.find_all("tr"):
        if "median" in clean(tr.get_text(" ")).lower()[:40] and not tr.select('a[href*="/company/"]'):
            cells = [clean(td.get_text()) for td in tr.find_all("td")]
            median = {headers[i] if i < len(headers) else "col%d" % i: num(c)
                      for i, c in enumerate(cells)
                      if num(c) is not None and i >= 2}           # skip S.No. and "Median: N Co."
            m_n = re.search(r"median:\s*(\d+)", clean(tr.get_text(" ")), re.I)
            if m_n:
                median["companies_in_median"] = int(m_n.group(1))
    return {"columns": headers, "peers": recs, "median": median}


def parse_screen_results(html: str) -> dict:
    """Screen results. Picks the table with the MOST /company/ links (the markup drifts).

    Approach adapted from the robust parser in LogeshR15/screener-mcp (MIT).
    """
    soup = _soup(html)
    best, best_n = None, 0
    for t in soup.find_all("table"):
        n = len(t.select('a[href*="/company/"]'))
        if n > best_n:
            best, best_n = t, n
    count = None
    m = re.search(r"([\d,]+)\s+results?\s+found", soup.get_text(" "), re.I)
    if m:
        count = int(m.group(1).replace(",", ""))
    if best is None:
        return {"count": count or 0, "columns": [], "companies": []}
    headers, recs = _table_records(best)
    return {"count": count if count is not None else len(recs), "columns": headers, "companies": recs}
