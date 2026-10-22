"""HTTP layer: cache → governor → request → classify → cache.

Every network request to Screener.in in this package goes through
``ScreenerClient.fetch`` — one choke point, so the politeness rules can't be
bypassed by a new feature.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

import httpx

from . import credentials
from .cache import PageCache
from .config import IST, TTL, Settings
from .errors import Blocked, BudgetExhausted, LoginFailed, LoginRequired, NotFound, ScreenerError
from .governor import Governor

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/134.0.0.0 Safari/537.36 screener-india-mcp/0.1"
)
_HTML_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.screener.in/",
}
_JSON_HEADERS = dict(_HTML_HEADERS, Accept="application/json, text/javascript, */*; q=0.01",
                     **{"X-Requested-With": "XMLHttpRequest"})

_BLOCK_STATUS = {403, 429, 503}
_BLOCK_BODY = re.compile(r"too many requests|access denied|request blocked|captcha|cf-chl", re.I)
_ANON_MARKERS = ("Get free account", "plausible-event-user=unregistered")


def is_anonymous_page(html: str) -> bool:
    """True if a Screener HTML page was served to a logged-out visitor."""
    if "/logout/" in html:
        return False
    return any(m in html for m in _ANON_MARKERS)


@dataclass
class Page:
    url: str
    body: bytes
    status: int
    fetched_at: float
    from_cache: bool
    stale: bool

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def provenance(self, **extra) -> dict:
        d = {
            "source_url": self.url,
            "fetched_at": datetime.fromtimestamp(self.fetched_at, IST).isoformat(timespec="seconds"),
            "from_cache": self.from_cache,
            "stale": self.stale,
        }
        d.update(extra)
        return d


class ScreenerClient:
    def __init__(self, settings: Optional[Settings] = None, transport: Optional[httpx.BaseTransport] = None,
                 governor: Optional[Governor] = None, cache: Optional[PageCache] = None):
        self.s = settings or Settings.from_env()
        self.s.ensure_dirs()
        self.gov = governor or Governor(self.s.state_dir, self.s.min_interval, self.s.budget_anon, self.s.budget_auth)
        self.cache = cache or PageCache(self.s.cache_dir)
        self.http = httpx.Client(base_url=self.s.base_url, timeout=self.s.timeout, follow_redirects=True,
                                 transport=transport)
        self._lock = threading.RLock()
        self.logged_in = False
        sess = credentials.load_session()
        if sess:
            for k, v in sess.items():
                self.http.cookies.set(k, v, domain="www.screener.in")
            self.logged_in = "sessionid" in sess

    # ------------------------------------------------------------ helpers
    def _url(self, path: str, params: Optional[dict]) -> str:
        q = ("?" + urlencode(params)) if params else ""
        return self.s.base_url + path + q

    def has_credentials(self) -> bool:
        return credentials.get_credentials() is not None

    def _send(self, method: str, path: str, *, params=None, data=None, json_api=False) -> httpx.Response:
        self.gov.acquire(authenticated=self.logged_in)
        headers = _JSON_HEADERS if json_api else _HTML_HEADERS
        try:
            if method == "POST":
                r = self.http.post(path, data=data, headers=dict(headers, Referer=self.s.base_url + path),
                                   follow_redirects=False)
            else:
                r = self.http.get(path, params=params, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            until = self.gov.report_block()
            raise Blocked(
                "Could not connect to Screener.in (it may be blocking this network, or the internet is down). "
                "Cooling down until %s IST." % datetime.fromtimestamp(until, IST).isoformat(timespec="seconds"),
                datetime.fromtimestamp(until, IST).isoformat(timespec="seconds"),
            ) from exc
        except httpx.HTTPError as exc:
            raise ScreenerError("Network error talking to Screener.in: %s" % exc) from exc
        if r.status_code in _BLOCK_STATUS or (r.status_code == 200 and not json_api
                                              and len(r.content) < 20000 and _BLOCK_BODY.search(r.text)):
            until = self.gov.report_block()
            iso = datetime.fromtimestamp(until, IST).isoformat(timespec="seconds")
            raise Blocked("Screener.in refused the request (HTTP %d). Cooling down until %s IST."
                          % (r.status_code, iso), iso)
        return r

    # ------------------------------------------------------------ login
    def login(self) -> bool:
        """Log in with the stored credentials. Never logs or returns the password."""
        creds = credentials.get_credentials()
        if not creds:
            raise LoginRequired(
                "This needs a (free) Screener.in account. Run `screener-india-mcp login` once in a terminal; "
                "the password is kept in your operating system's secure store."
            )
        email, password = creds
        with self._lock:
            r = self._send("GET", "/login/")
            m = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', r.text)
            token = m.group(1) if m else self.http.cookies.get("csrftoken")
            if not token:
                raise LoginFailed("Screener.in login page changed: no CSRF token found.")
            r = self._send("POST", "/login/", data={"username": email, "password": password,
                                                    "csrfmiddlewaretoken": token, "next": "/"})
            # Success = a redirect away from /login/ plus a session cookie (we don't follow the redirect:
            # that would be one more request to Screener for nothing).
            location = r.headers.get("location", "")
            ok = ("sessionid" in self.http.cookies and r.status_code in (301, 302, 303)
                  and "/login/" not in location)
            if not ok:
                self.logged_in = False
                raise LoginFailed("Screener.in rejected the stored email/password. Run `screener-india-mcp login` again.")
            self.logged_in = True
            credentials.save_session({c.name: c.value for c in self.http.cookies.jar})
            self.gov.report_ok()
            return True

    # ------------------------------------------------------------ fetch
    def fetch(self, path: str, *, params: Optional[dict] = None, kind: str = "company",
              json_api: bool = False, need_login: bool = False, allow_stale: bool = True) -> Page:
        url = self._url(path, params)
        key = ("auth:" if need_login else "") + url
        ttl = TTL.get(kind, 3600)
        hit = self.cache.get(key, ttl)
        if hit:
            body, status, ts, _ = hit
            if status == 404:
                raise NotFound("Not found on Screener.in: %s" % url)
            return Page(url, body, status, ts, True, False)

        with self._lock:
            try:
                if need_login and not self.logged_in:
                    self.login()
                r = self._send("GET", path, params=params, json_api=json_api)
                final = str(r.url)
                if need_login and ("/login/" in final or "/register/" in final
                                   or (not json_api and is_anonymous_page(r.text))):
                    # Screener ended the session silently: log in again once.
                    self.logged_in = False
                    self.login()
                    r = self._send("GET", path, params=params, json_api=json_api)
                    final = str(r.url)
                    if "/login/" in final or "/register/" in final:
                        raise LoginRequired("Screener.in still asks for a login for this page.")
            except (Blocked, BudgetExhausted):
                if allow_stale:
                    old = self.cache.get(key, ttl, allow_stale=True)
                    if old and old[1] == 200:
                        return Page(url, old[0], 200, old[2], True, True)
                raise

        if r.status_code == 404:
            self.cache.put(key, b"", 404)
            raise NotFound("Not found on Screener.in: %s" % url)
        if r.status_code >= 400:
            raise ScreenerError("Screener.in returned HTTP %d for %s" % (r.status_code, url))
        self.gov.report_ok()
        ts = self.cache.put(key, r.content, r.status_code)
        return Page(url, r.content, r.status_code, ts, False, False)

    def status(self) -> dict:
        return {
            "logged_in": self.logged_in,
            "credentials": credentials.credential_source(),
            "governor": self.gov.status(authenticated=self.logged_in),
            "cache": self.cache.stats(),
        }

    def close(self) -> None:
        self.http.close()
