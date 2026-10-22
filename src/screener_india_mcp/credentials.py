"""Credentials live in the operating system's own secure store.

* Windows: Credential Manager · macOS: Keychain · Linux: Secret Service (GNOME Keyring / KWallet)

You type the password once with ``screener-india-mcp login`` (hidden input).
The server logs in again by itself whenever Screener ends the session.
There is deliberately NO MCP tool that accepts a password, so it never passes
through an AI conversation.

Fallback for headless Linux boxes without a keyring: environment variables
``SCREENER_EMAIL`` and ``SCREENER_PASSWORD`` (less safe; documented as such).
"""

from __future__ import annotations

import json
import os
from typing import Optional, Tuple

SERVICE = "screener-india-mcp"
_EMAIL_KEY = "__email__"
_SESSION_KEY = "__session__"


def _keyring():
    try:
        import keyring  # noqa: WPS433
        from keyring.errors import NoKeyringError  # noqa: F401

        return keyring
    except Exception:  # pragma: no cover - keyring import problems
        return None


def keyring_available() -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        backend = kr.get_keyring()
        name = type(backend).__name__.lower()
        return "fail" not in name and "null" not in name
    except Exception:
        return False


def save_credentials(email: str, password: str) -> None:
    kr = _keyring()
    if not keyring_available():
        raise RuntimeError(
            "No operating-system keyring is available on this machine. Use the "
            "SCREENER_EMAIL / SCREENER_PASSWORD environment variables instead."
        )
    kr.set_password(SERVICE, _EMAIL_KEY, email)
    kr.set_password(SERVICE, email, password)


def get_credentials() -> Optional[Tuple[str, str]]:
    env_e, env_p = os.environ.get("SCREENER_EMAIL"), os.environ.get("SCREENER_PASSWORD")
    if env_e and env_p:
        return env_e, env_p
    if not keyring_available():
        return None
    kr = _keyring()
    try:
        email = kr.get_password(SERVICE, _EMAIL_KEY)
        if not email:
            return None
        pw = kr.get_password(SERVICE, email)
        return (email, pw) if pw else None
    except Exception:
        return None


def credential_source() -> str:
    if os.environ.get("SCREENER_EMAIL") and os.environ.get("SCREENER_PASSWORD"):
        return "environment variables"
    if keyring_available() and get_credentials():
        return "operating-system keyring"
    return "none (anonymous mode)"


def save_session(cookies: dict) -> None:
    if not keyring_available():
        return
    keep = {k: v for k, v in cookies.items() if k in ("sessionid", "csrftoken")}
    try:
        _keyring().set_password(SERVICE, _SESSION_KEY, json.dumps(keep))
    except Exception:
        pass


def load_session() -> dict:
    if not keyring_available():
        return {}
    try:
        raw = _keyring().get_password(SERVICE, _SESSION_KEY)
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def clear_all() -> None:
    if not keyring_available():
        return
    kr = _keyring()
    try:
        email = kr.get_password(SERVICE, _EMAIL_KEY)
    except Exception:
        email = None
    for key in filter(None, (email, _EMAIL_KEY, _SESSION_KEY)):
        try:
            kr.delete_password(SERVICE, key)
        except Exception:
            pass
