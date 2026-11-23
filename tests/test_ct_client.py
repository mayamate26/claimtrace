"""Client request shape and error mapping, against httpx.MockTransport."""

import json

import httpx
import pytest

import claimtrace_mcp
from claimtrace_mcp import client

RESULT = {"claims": [{"label": "SUPPORTED", "sentence": "GDP grew 2.1%.", "number": "2.1%", "span": "grew 2.1 percent"}],
          "summary": {"total": 1, "supported": 1, "mismatch": 0, "unsupported": 0, "errors": 0}, "notices": []}


def _recorder(status=200, body=None):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(status, json=RESULT if body is None else body)

    return seen, httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("CLAIMTRACE_API_KEY", raising=False)
    monkeypatch.delenv("CLAIMTRACE_API_BASE", raising=False)


def test_json_request_shape_and_bearer():
    seen, t = _recorder()
    out = claimtrace_mcp.check("GDP grew 2.1%.", ["https://stats.example/gdp", "pasted source"], share=True,
                           api_key="k-123", transport=t)
    assert out == RESULT
    req = seen[0]
    assert req.method == "POST" and str(req.url) == "https://claimtrace-api.fly.dev/api/check"
    assert req.headers["authorization"] == "Bearer k-123"
    assert json.loads(req.content) == {
        "document": "GDP grew 2.1%.", "share": True,
        "sources": [{"kind": "url", "value": "https://stats.example/gdp"}, {"kind": "text", "value": "pasted source"}]}


def test_no_key_means_no_auth_header_and_env_overrides(monkeypatch):
    monkeypatch.setenv("CLAIMTRACE_API_BASE", "http://localhost:8080/")
    seen, t = _recorder()
    claimtrace_mcp.check("x 1", [{"kind": "text", "value": "y"}], transport=t)
    assert str(seen[0].url) == "http://localhost:8080/api/check"
    assert "authorization" not in seen[0].headers
    monkeypatch.setenv("CLAIMTRACE_API_KEY", "env-key")
    claimtrace_mcp.check("x 1", ["y"], transport=t, api_base="https://other.example")
    assert seen[1].headers["authorization"] == "Bearer env-key"
    assert str(seen[1].url) == "https://other.example/api/check"


def test_pdf_upload_is_multipart(tmp_path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    seen, t = _recorder()
    claimtrace_mcp.check("Revenue was $5m.", ["https://a.example"], pdfs=[pdf, ("second.pdf", b"%PDF two")],
                     share=False, api_key="k", transport=t)
    req = seen[0]
    assert req.headers["content-type"].startswith("multipart/form-data")
    assert req.headers["authorization"] == "Bearer k"
    body = req.content.decode("latin-1")
    assert 'name="document"' in body and "Revenue was $5m." in body
    assert 'name="sources"' in body and json.dumps([{"kind": "url", "value": "https://a.example"}]) in body
    assert 'name="share"' in body and "false" in body
    assert 'filename="report.pdf"' in body and "%PDF-1.4 fake" in body
    assert 'filename="second.pdf"' in body and "application/pdf" in body


@pytest.mark.parametrize("status,exc", [(401, claimtrace_mcp.AuthError), (429, claimtrace_mcp.RateLimitError),
                                        (503, claimtrace_mcp.UnavailableError), (400, claimtrace_mcp.APIError),
                                        (500, claimtrace_mcp.APIError)])
def test_errors_carry_the_server_message(status, exc):
    _, t = _recorder(status, {"error": "You've used your free 10 claims for today."})
    with pytest.raises(exc) as info:
        claimtrace_mcp.check("a 1", ["b"], transport=t)
    assert info.value.status == status
    assert info.value.message == "You've used your free 10 claims for today."
    assert isinstance(info.value, claimtrace_mcp.ClaimTraceError)


def test_network_failure_is_an_api_error():
    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(claimtrace_mcp.APIError, match="could not reach"):
        claimtrace_mcp.check("a 1", ["b"], transport=httpx.MockTransport(boom))


def test_source_spec_classification():
    assert client.source_spec("https://x.example/a") == {"kind": "url", "value": "https://x.example/a"}
    assert client.source_spec("  HTTP://x.example ") == {"kind": "url", "value": "HTTP://x.example"}
    assert client.source_spec("ftp://not-a-url-for-us") == {"kind": "text", "value": "ftp://not-a-url-for-us"}
    assert client.source_spec("The rate was 4%.") == {"kind": "text", "value": "The rate was 4%."}
    assert client.source_spec({"kind": "URL", "value": "https://y"}) == {"kind": "url", "value": "https://y"}
    with pytest.raises(ValueError):
        client.source_spec({"kind": "pdf", "value": "x"})


def test_report_and_badge():
    def handler(request):
        if request.url.path == "/r/abc123.json":
            return httpx.Response(200, json={"summary": RESULT["summary"]})
        if request.url.path == "/badge/abc123.svg":
            return httpx.Response(200, text="<svg/>", headers={"content-type": "image/svg+xml"})
        return httpx.Response(404, json={"error": "Report not found (shared reports are deleted after 30 days)."})

    t = httpx.MockTransport(handler)
    assert claimtrace_mcp.get_report("abc123", transport=t) == {"summary": RESULT["summary"]}
    assert claimtrace_mcp.get_badge("abc123", transport=t) == "<svg/>"
    with pytest.raises(claimtrace_mcp.APIError, match="deleted after 30 days"):
        claimtrace_mcp.get_report("zzzzzz", transport=t)
