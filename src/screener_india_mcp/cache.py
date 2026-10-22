"""Small SQLite page cache (standard library only).

Fresh copies are reused without touching Screener.in. When Screener refuses us
or the daily budget is spent, the last copy is served marked ``stale``.
The cache is local to the user's machine and is never shared or published.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path


class PageCache:
    def __init__(self, cache_dir: Path, clock=time.time):
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.path = cache_dir / "pages.sqlite"
        self.clock = clock
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS pages (key TEXT PRIMARY KEY, body BLOB NOT NULL, "
                "status INTEGER NOT NULL, fetched_at REAL NOT NULL)"
            )

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.path), timeout=30)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def get(self, key: str, ttl: float, allow_stale: bool = False):
        """Return (body, status, fetched_at, is_stale) or None."""
        with self._lock, self._conn() as c:
            row = c.execute("SELECT body, status, fetched_at FROM pages WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        body, status, fetched_at = row
        stale = (self.clock() - fetched_at) > ttl
        if stale and not allow_stale:
            return None
        return bytes(body), int(status), float(fetched_at), stale

    def put(self, key: str, body: bytes, status: int = 200) -> float:
        now = self.clock()
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO pages (key, body, status, fetched_at) VALUES (?,?,?,?)",
                (key, body, status, now),
            )
        return now

    def stats(self) -> dict:
        with self._lock, self._conn() as c:
            n, size = c.execute("SELECT COUNT(*), COALESCE(SUM(LENGTH(body)),0) FROM pages").fetchone()
        return {"pages": n, "bytes": size, "path": str(self.path)}

    def clear(self) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM pages")
