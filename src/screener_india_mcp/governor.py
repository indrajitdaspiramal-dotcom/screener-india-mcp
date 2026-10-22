"""Machine-wide politeness governor.

Every process on the machine that uses this package (the MCP server, the CLI,
a nightly script) shares ONE state file guarded by a file lock, so together
they never exceed:

* one request every ``min_interval`` seconds,
* ``budget`` requests per IST calendar day,
* and nothing at all during a cool-down after Screener.in refused us.

This is the main thing other Screener tools get wrong: each process throttles
itself, so two or three of them running at once still trip Screener's limits.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from filelock import FileLock

from .config import COOLDOWN_STEPS, IST
from .errors import Blocked, BudgetExhausted


def _today(now: float) -> str:
    return datetime.fromtimestamp(now, IST).strftime("%Y-%m-%d")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, IST).isoformat(timespec="seconds")


def _next_midnight(now: float) -> float:
    d = datetime.fromtimestamp(now, IST).replace(hour=0, minute=0, second=0, microsecond=0)
    return (d + timedelta(days=1)).timestamp()


class Governor:
    def __init__(
        self,
        state_dir: Path,
        min_interval: float,
        budget_anon: int,
        budget_auth: int,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ):
        state_dir.mkdir(parents=True, exist_ok=True)
        self.path = state_dir / "governor.json"
        self.lock = FileLock(str(state_dir / "governor.lock"), timeout=600)
        self.min_interval = min_interval
        self.budget_anon = budget_anon
        self.budget_auth = budget_auth
        self.clock = clock
        self.sleep = sleep

    # ------------------------------------------------------------------ state
    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, st: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st), encoding="utf-8")
        tmp.replace(self.path)

    def _rolled(self, st: dict, now: float) -> dict:
        if st.get("day") != _today(now):
            st["day"] = _today(now)
            st["count"] = 0
        st.setdefault("count", 0)
        st.setdefault("last", 0.0)
        st.setdefault("strikes", 0)
        st.setdefault("cooldown_until", 0.0)
        return st

    # ------------------------------------------------------------------ API
    def acquire(self, authenticated: bool) -> None:
        """Block until a request is allowed, then record it. Raises if not allowed today."""
        with self.lock:
            now = self.clock()
            st = self._rolled(self._load(), now)
            if now < st["cooldown_until"]:
                raise Blocked(
                    "Screener.in refused recent requests, so this server is cooling down "
                    "until %s IST to avoid a longer block." % _iso(st["cooldown_until"]),
                    _iso(st["cooldown_until"]),
                )
            budget = self.budget_auth if authenticated else self.budget_anon
            if st["count"] >= budget:
                raise BudgetExhausted(
                    "Today's Screener.in request budget (%d) is used up; it resets at midnight IST. "
                    "Cached data is still served." % budget,
                    _iso(_next_midnight(now)),
                )
            wait = st["last"] + self.min_interval - now
            if wait > 0:
                self.sleep(wait)
                now = self.clock()
            st["count"] += 1
            st["last"] = now
            self._save(st)

    def report_ok(self) -> None:
        with self.lock:
            st = self._rolled(self._load(), self.clock())
            if st["strikes"]:
                st["strikes"] = 0
                self._save(st)

    def report_block(self) -> float:
        """Start (or lengthen) a cool-down. Returns the time it ends."""
        with self.lock:
            now = self.clock()
            st = self._rolled(self._load(), now)
            st["strikes"] += 1
            step = COOLDOWN_STEPS[min(st["strikes"], len(COOLDOWN_STEPS)) - 1]
            st["cooldown_until"] = max(st["cooldown_until"], now + step)
            self._save(st)
            return st["cooldown_until"]

    def status(self, authenticated: bool) -> dict:
        with self.lock:
            now = self.clock()
            st = self._rolled(self._load(), now)
        budget = self.budget_auth if authenticated else self.budget_anon
        cooling = now < st["cooldown_until"]
        return {
            "requests_today": st["count"],
            "daily_budget": budget,
            "remaining_today": max(0, budget - st["count"]),
            "min_seconds_between_requests": self.min_interval,
            "cooling_down": cooling,
            "cooldown_until": _iso(st["cooldown_until"]) if cooling else None,
            "recent_refusals": st["strikes"],
        }
