"""v0.1.3: the owner of a logged-in account can switch the daily cap off; nothing else gets less polite."""
from screener_india_mcp import config
from screener_india_mcp.config import Settings, auth_budget, UNLIMITED, MIN_INTERVAL_FLOOR, BUDGET_CEILING_ANON


def test_zero_switches_the_logged_in_cap_off(monkeypatch):
    monkeypatch.setenv("SCREENER_DAILY_BUDGET", "0")
    assert Settings.from_env().budget_auth == UNLIMITED


def test_other_values_stay_inside_the_ceiling(monkeypatch):
    assert auth_budget(5000) == config.BUDGET_CEILING_AUTH
    assert auth_budget(-3) == 1
    assert auth_budget(250) == 250


def test_spacing_and_anonymous_cap_never_loosen(monkeypatch):
    monkeypatch.setenv("SCREENER_DAILY_BUDGET", "0")
    monkeypatch.setenv("SCREENER_MIN_INTERVAL", "0.1")
    monkeypatch.setenv("SCREENER_DAILY_BUDGET_ANON", "100000")
    s = Settings.from_env()
    assert s.min_interval == MIN_INTERVAL_FLOOR
    assert s.budget_anon == BUDGET_CEILING_ANON
