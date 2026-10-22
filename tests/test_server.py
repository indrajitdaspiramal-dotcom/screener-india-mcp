import asyncio

from screener_india_mcp import server


def tools():
    return asyncio.run(server.mcp.list_tools())


def test_every_tool_is_read_only():
    ts = tools()
    assert len(ts) == 14
    for t in ts:
        assert t.annotations is not None and t.annotations.readOnlyHint is True, t.name
        assert t.annotations.destructiveHint is False, t.name


def test_no_tool_takes_a_password_or_path():
    for t in tools():
        props = (t.inputSchema or {}).get("properties", {})
        for name in props:
            assert "pass" not in name.lower() and "path" not in name.lower() and "file" not in name.lower(), (t.name, name)
        assert "login" not in t.name or t.name == "service_status"


def test_errors_become_dicts(monkeypatch):
    from screener_india_mcp.errors import Blocked

    class Boom:
        def overview(self, *a, **k):
            raise Blocked("cooling down", "2026-01-01T00:00:00+05:30")

    monkeypatch.setattr(server, "_svc", Boom())
    out = server.company_overview("X")
    assert out["error_type"] == "Blocked" and out["retry_after"].startswith("2026")
