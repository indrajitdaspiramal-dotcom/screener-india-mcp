"""Errors returned to the assistant as clear, actionable messages."""

from __future__ import annotations


class ScreenerError(Exception):
    """Base error."""

    kind = "error"

    def to_dict(self) -> dict:
        return {"error": str(self), "error_type": type(self).__name__}


class NotFound(ScreenerError):
    """The symbol or page does not exist on Screener.in."""


class LoginRequired(ScreenerError):
    """The feature needs a Screener.in account (run `screener-india-mcp login`)."""


class LoginFailed(ScreenerError):
    """Screener.in rejected the stored credentials."""


class Blocked(ScreenerError):
    """Screener.in is refusing requests; we are cooling down."""

    def __init__(self, message: str, until_iso: str | None = None):
        super().__init__(message)
        self.until_iso = until_iso

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["retry_after"] = self.until_iso
        return d


class BudgetExhausted(ScreenerError):
    """Today's request budget is used up (resets at midnight IST)."""

    def __init__(self, message: str, resets_iso: str | None = None):
        super().__init__(message)
        self.resets_iso = resets_iso

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["retry_after"] = self.resets_iso
        return d


class ParseError(ScreenerError):
    """The page layout was not what we expected (Screener may have changed it)."""
