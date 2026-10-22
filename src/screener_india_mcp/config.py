"""Settings. Environment variables may make the server MORE polite, never less.

Hard floors exist on purpose: Screener.in is a small Indian company that serves
the public for free. A tool that hammers it gets everyone blocked.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path

import platformdirs

APP = "screener-india-mcp"
BASE_URL = "https://www.screener.in"
IST = timezone(timedelta(hours=5, minutes=30))

# Floors / ceilings users cannot override.
MIN_INTERVAL_FLOOR = 2.0          # seconds between any two requests, machine-wide
BUDGET_CEILING_ANON = 60          # requests per IST day without a login
BUDGET_CEILING_AUTH = 1000        # requests per IST day with a login

# Cool-down after Screener refuses us: 30 min, 2 h, 6 h, then 24 h.
COOLDOWN_STEPS = (30 * 60, 2 * 3600, 6 * 3600, 24 * 3600)

# How long a fetched page stays fresh (seconds).
TTL = {
    "company": 6 * 3600,
    "peers": 6 * 3600,
    "chart": 3 * 3600,
    "search": 7 * 24 * 3600,
    "screen": 3600,
    "login": 0,
    "notfound": 24 * 3600,
}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    base_url: str = BASE_URL
    min_interval: float = 3.0
    budget_anon: int = 40
    budget_auth: int = 300
    timeout: float = 30.0
    state_dir: Path = field(default_factory=lambda: Path(platformdirs.user_state_dir(APP, appauthor=False)))
    cache_dir: Path = field(default_factory=lambda: Path(platformdirs.user_cache_dir(APP, appauthor=False)))

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls()
        s.min_interval = max(MIN_INTERVAL_FLOOR, _env_float("SCREENER_MIN_INTERVAL", s.min_interval))
        s.budget_anon = max(1, min(BUDGET_CEILING_ANON, _env_int("SCREENER_DAILY_BUDGET_ANON", s.budget_anon)))
        s.budget_auth = max(1, min(BUDGET_CEILING_AUTH, _env_int("SCREENER_DAILY_BUDGET", s.budget_auth)))
        s.timeout = max(5.0, _env_float("SCREENER_TIMEOUT", s.timeout))
        if os.environ.get("SCREENER_STATE_DIR"):
            s.state_dir = Path(os.environ["SCREENER_STATE_DIR"])
        if os.environ.get("SCREENER_CACHE_DIR"):
            s.cache_dir = Path(os.environ["SCREENER_CACHE_DIR"])
        return s

    def ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
