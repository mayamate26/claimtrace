"""The MCP tool logic, tested without the mcp package."""

import builtins
import sys

import pytest

from claimtrace_mcp import mcp_server
from claimtrace_mcp.client import AuthError

RESULT = {"claims": [], "summary": {"total": 2, "supported": 1, "mismatch": 1, "unsupported": 0, "errors": 0},
          "notices": [], "share_url": "https://claimtrace-api.fly.dev/r/abc123"}


def test_check_numbers_classifies_sources_and_summarises():
    calls = []

    def fake(document, specs, share=False):
        calls.append((document, specs, share))
        return RESULT

    out = mcp_server.check_numbers("Doc with 2 numbers: 5 and 6.", ["https://a.example/x", "pasted text 5", "  "],
                                   share=True, check_fn=fake)
    assert calls == [("Doc with 2 numbers: 5 and 6.",
                      [{"kind": "url", "value": "https://a.example/x"}, {"kind": "text", "value": "pasted text 5"}], True)]
    assert out["ledger"] is RESULT
    assert out["summary"] == ("1/2 numbers supported, 1 mismatch, 0 unsupported. "
                              "Report: https://claimtrace-api.fly.dev/r/abc123")


def test_check_numbers_needs_a_source_and_wraps_api_errors():
    with pytest.raises(ValueError, match="at least one source"):
        mcp_server.check_numbers("a 1", [], check_fn=lambda *a, **k: RESULT)

    def denied(*a, **k):
        raise AuthError("Unknown API key.", 401)

    with pytest.raises(RuntimeError, match="Unknown API key"):
        mcp_server.check_numbers("a 1", ["b"], check_fn=denied)


def test_missing_mcp_package_is_a_friendly_error(monkeypatch):
    real_import = builtins.__import__

    def no_mcp(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    for mod in [m for m in sys.modules if m == "mcp" or m.startswith("mcp.")]:
        monkeypatch.delitem(sys.modules, mod)
    monkeypatch.setattr(builtins, "__import__", no_mcp)
    with pytest.raises(mcp_server.MissingMCP, match=r"pip install claimtrace-mcp"):
        mcp_server.build_server()


def test_base_package_does_not_import_mcp():
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    code = "import sys, claimtrace_mcp, claimtrace_mcp.cli, claimtrace_mcp.mcp_server, claimtrace_mcp.action_runner; print('mcp' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_real_server_registers_the_tool_when_mcp_is_installed():
    pytest.importorskip("mcp")
    import asyncio

    server = mcp_server.build_server()
    tools = asyncio.run(server.list_tools())
    assert [t.name for t in tools] == ["check_numbers"]
    tool = tools[0]
    schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema")
    assert set(schema["properties"]) == {"document", "sources", "share"}
    assert set(schema["required"]) == {"document", "sources"}


def test_claimtrace_mcp_entry_point_starts_the_server(monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server, "serve", lambda: calls.append(1))
    assert mcp_server.main() == 0 and calls == [1]


def test_claimtrace_mcp_entry_point_without_mcp_is_a_friendly_error(monkeypatch, capsys):
    def missing():
        raise mcp_server.MissingMCP("the MCP server needs the 'mcp' package: pip install claimtrace-mcp")

    monkeypatch.setattr(mcp_server, "serve", missing)
    assert mcp_server.main() == 2
    assert "pip install claimtrace-mcp" in capsys.readouterr().err
