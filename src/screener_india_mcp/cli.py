"""Command line.

    screener-india-mcp                 run the MCP server over stdio (what MCP clients launch)
    screener-india-mcp serve [--http]  same, or over streamable HTTP on 127.0.0.1:8631
    screener-india-mcp login           store your Screener.in login in the OS secure store (hidden prompt)
    screener-india-mcp logout          remove it
    screener-india-mcp status          login state, today's budget, cool-down, cache
    screener-india-mcp get SYMBOL      print a company snapshot (handy for testing)
"""

from __future__ import annotations

import argparse
import getpass
import sys

from . import __version__, credentials


def _cmd_login(args) -> int:
    if not credentials.keyring_available():
        print("No operating-system keyring is available here. Set SCREENER_EMAIL and SCREENER_PASSWORD "
              "environment variables instead (less safe).", file=sys.stderr)
        return 2
    email = args.email or input("Screener.in email: ").strip()
    password = getpass.getpass("Screener.in password (hidden): ")
    if not email or not password:
        print("Email and password are both required.", file=sys.stderr)
        return 2
    credentials.save_credentials(email, password)
    del password
    from .client import ScreenerClient
    from .errors import ScreenerError

    try:
        ScreenerClient().login()
    except ScreenerError as exc:
        print("Saved, but the test login failed: %s" % exc, file=sys.stderr)
        return 1
    print("Logged in. Your password is in the %s; this tool will log in again by itself when needed."
          % credentials.credential_source())
    return 0


def _cmd_logout(_args) -> int:
    credentials.clear_all()
    print("Removed the stored Screener.in login and session.")
    return 0


def _cmd_status(_args) -> int:
    from .service import Screener, to_json

    print(to_json(Screener().status()))
    return 0


def _cmd_get(args) -> int:
    from .errors import ScreenerError
    from .service import Screener, to_json

    try:
        print(to_json(Screener().snapshot(args.symbol)))
        return 0
    except ScreenerError as exc:
        print(to_json(exc.to_dict()))
        return 1


def _cmd_serve(args) -> int:
    from .server import run

    run("http" if args.http else "stdio", args.host, args.port)
    return 0


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="screener-india-mcp", description="Screener India MCP server and helper commands.")
    p.add_argument("--version", action="version", version="screener-india-mcp %s" % __version__)
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="run the MCP server")
    s.add_argument("--http", action="store_true", help="streamable HTTP instead of stdio")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8631)
    s.set_defaults(fn=_cmd_serve)
    lg = sub.add_parser("login", help="store your Screener.in login securely")
    lg.add_argument("--email")
    lg.set_defaults(fn=_cmd_login)
    sub.add_parser("logout", help="remove the stored login").set_defaults(fn=_cmd_logout)
    sub.add_parser("status", help="show login, budget and cache status").set_defaults(fn=_cmd_status)
    g = sub.add_parser("get", help="print a company snapshot")
    g.add_argument("symbol")
    g.set_defaults(fn=_cmd_get)
    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        args = p.parse_args(["serve"])
    sys.exit(args.fn(args))
