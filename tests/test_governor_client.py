import httpx
import pytest
from conftest import fixture_text

from screener_india_mcp import credentials
from screener_india_mcp.cache import PageCache
from screener_india_mcp.client import ScreenerClient, is_anonymous_page
from screener_india_mcp.config import Settings
from screener_india_mcp.errors import Blocked, BudgetExhausted, LoginRequired, NotFound
from screener_india_mcp.governor import Governor
from screener_india_mcp.service import Screener


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def make(tmp_path, handler, budget_anon=40, clock=None):
    clock = clock or Clock()
    s = Settings.from_env()
    gov = Governor(s.state_dir, 3.0, budget_anon, 300, clock=clock, sleep=clock.sleep)
    cache = PageCache(s.cache_dir, clock=clock)
    calls = []

    def h(req):
        calls.append(req)
        return handler(req)

    c = ScreenerClient(s, transport=httpx.MockTransport(h), governor=gov, cache=cache)
    return c, calls, clock


def ok_company(req):
    return httpx.Response(200, text=fixture_text("company_example.html"))


# ---------------------------------------------------------------- governor
def test_spacing_and_budget(tmp_path):
    clock = Clock()
    g = Governor(tmp_path / "g", 3.0, 2, 10, clock=clock, sleep=clock.sleep)
    g.acquire(False)
    g.acquire(False)
    assert clock.slept == [3.0]
    with pytest.raises(BudgetExhausted):
        g.acquire(False)
    g.acquire(True)                      # logged-in budget is separate and larger


def test_budget_resets_next_ist_day(tmp_path):
    clock = Clock()
    g = Governor(tmp_path / "g", 3.0, 1, 10, clock=clock, sleep=clock.sleep)
    g.acquire(False)
    clock.t += 86400
    g.acquire(False)


def test_shared_state_across_instances(tmp_path):
    clock = Clock()
    a = Governor(tmp_path / "g", 3.0, 2, 10, clock=clock, sleep=clock.sleep)
    b = Governor(tmp_path / "g", 3.0, 2, 10, clock=clock, sleep=clock.sleep)
    a.acquire(False)
    b.acquire(False)
    with pytest.raises(BudgetExhausted):
        a.acquire(False)


def test_cooldown_escalates(tmp_path):
    clock = Clock()
    g = Governor(tmp_path / "g", 3.0, 40, 300, clock=clock, sleep=clock.sleep)
    first = g.report_block()
    assert first - clock.t == 30 * 60
    with pytest.raises(Blocked):
        g.acquire(False)
    clock.t = first + 1
    second = g.report_block()
    assert second - clock.t == 2 * 3600
    g.report_ok()
    assert g.status(False)["recent_refusals"] == 0


def test_env_cannot_make_it_aggressive(monkeypatch):
    monkeypatch.setenv("SCREENER_MIN_INTERVAL", "0.1")
    monkeypatch.setenv("SCREENER_DAILY_BUDGET_ANON", "100000")
    s = Settings.from_env()
    assert s.min_interval == 2.0 and s.budget_anon == 60


# ---------------------------------------------------------------- client
def test_cache_means_one_request(tmp_path):
    c, calls, _ = make(tmp_path, ok_company)
    svc = Screener(c)
    svc.overview("EXAMPLE")
    svc.red_flags("EXAMPLE")
    svc.earnings_trend("EXAMPLE")
    svc.documents("EXAMPLE")
    assert len(calls) == 1
    out = svc.overview("example")
    assert out["provenance"]["from_cache"] is True and out["provenance"]["view"] == "consolidated"


def test_block_sets_cooldown_and_serves_stale(tmp_path):
    state = {"n": 0}

    def handler(req):
        state["n"] += 1
        return ok_company(req) if state["n"] == 1 else httpx.Response(429, text="Too Many Requests")

    c, calls, clock = make(tmp_path, handler)
    svc = Screener(c)
    svc.overview("EXAMPLE")
    clock.t += 7 * 3600                                   # page is now past its 6-hour freshness
    out = svc.overview("EXAMPLE")                         # 429 -> cooldown -> stale copy
    assert out["provenance"]["stale"] is True
    n = len(calls)
    out = svc.overview("EXAMPLE")                         # during cooldown: no network at all
    assert len(calls) == n and out["provenance"]["stale"] is True


def test_block_without_cache_raises(tmp_path):
    c, _, _ = make(tmp_path, lambda r: httpx.Response(503, text="busy"))
    with pytest.raises(Blocked):
        Screener(c).overview("NEWCO")


def test_connect_error_counts_as_block(tmp_path):
    def handler(req):
        raise httpx.ConnectError("refused")

    c, _, _ = make(tmp_path, handler)
    with pytest.raises(Blocked):
        Screener(c).overview("EXAMPLE")
    assert c.gov.status(False)["cooling_down"] is True


def test_not_found_is_cached(tmp_path):
    c, calls, _ = make(tmp_path, lambda r: httpx.Response(404, text="nope"))
    svc = Screener(c)
    with pytest.raises(NotFound):
        svc.overview("NOSUCH")
    n = len(calls)
    with pytest.raises(NotFound):
        svc.overview("NOSUCH")
    assert len(calls) == n


def test_screen_needs_login(tmp_path):
    c, _, _ = make(tmp_path, ok_company)
    with pytest.raises(LoginRequired):
        Screener(c).run_screen("ROCE > 20")


def test_login_and_silent_relogin(tmp_path, no_real_keyring):
    credentials.save_credentials("me@example.org", "s3cret")
    seen = {"logins": 0, "screens": 0}

    def handler(req):
        if req.url.path == "/login/" and req.method == "GET":
            return httpx.Response(200, text='<input name="csrfmiddlewaretoken" value="tok123">')
        if req.url.path == "/login/" and req.method == "POST":
            seen["logins"] += 1
            body = req.content.decode()
            assert "csrfmiddlewaretoken=tok123" in body
            return httpx.Response(302, headers={"location": "/dash/",
                                                "set-cookie": "sessionid=abc; Path=/; Domain=www.screener.in"})
        if req.url.path == "/dash/":
            return httpx.Response(200, text='<a href="/logout/">Logout</a>')
        if req.url.path == "/screen/raw/":
            seen["screens"] += 1
            if seen["screens"] == 1:                       # session silently expired -> anonymous page
                return httpx.Response(200, text='<a href="/register/">Get free account</a>')
            return httpx.Response(200, text=fixture_text("screen_example.html"))
        return httpx.Response(404)

    c, calls, _ = make(tmp_path, handler)
    res = Screener(c).run_screen("Return on capital employed > 20")
    assert seen["logins"] == 2 and res["count"] == 37
    assert "s3cret" not in str(res)
    assert credentials.load_session().get("sessionid") == "abc"


def test_anonymous_marker():
    assert is_anonymous_page(fixture_text("company_example.html"))
    assert not is_anonymous_page(fixture_text("company_example_loggedin.html"))
