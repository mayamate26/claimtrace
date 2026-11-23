"""CLI: exit codes, formats, source classification."""

import io
import json

import pytest

from claimtrace_mcp import cli
from claimtrace_mcp.client import RateLimitError


def _result(mismatch=0, unsupported=0, supported=1):
    claims = ([{"label": "SUPPORTED", "sentence": "Sales rose 12% in 2025 according to the annual report.",
                "number": "12%", "span": "sales increased 12 percent"}] * supported
              + [{"label": "MISMATCH", "sentence": "Costs | fell 3%.", "number": "3%", "span": "costs fell 5%"}] * mismatch
              + [{"label": "UNSUPPORTED", "sentence": "Margins hit 40%.", "number": "40%", "span": ""}] * unsupported)
    total = supported + mismatch + unsupported
    return {"claims": claims, "notices": [],
            "summary": {"total": total, "supported": supported, "mismatch": mismatch, "unsupported": unsupported, "errors": 0}}


class Fake:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result or _result(), exc, []

    def __call__(self, document, sources, **kw):
        self.calls.append((document, sources, kw))
        if self.exc:
            raise self.exc
        return self.result


def _run(argv, fake, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, check_fn=fake, stdout=out, stderr=err, stdin=io.StringIO(stdin))
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def doc(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("Sales rose 12% in 2025.")
    return p


def test_classify_source(tmp_path):
    txt, pdf = tmp_path / "notes.txt", tmp_path / "Report.PDF"
    txt.write_text("rate 4%")
    pdf.write_bytes(b"%PDF")
    assert cli.classify_source(str(txt)) == ("text", "rate 4%")
    assert cli.classify_source(str(pdf)) == ("pdf", pdf)
    assert cli.classify_source("https://x.example/a") == ("url", "https://x.example/a")
    assert cli.classify_source(str(tmp_path / "missing.txt")) == ("url", str(tmp_path / "missing.txt"))
    specs, pdfs = cli.split_sources([str(txt), str(pdf), "https://x.example"])
    assert specs == [{"kind": "text", "value": "rate 4%"}, {"kind": "url", "value": "https://x.example"}]
    assert pdfs == [pdf]


def test_table_output_and_exit_zero(doc):
    fake = Fake()
    code, out, _ = _run(["check", str(doc), "--source", "https://x.example", "--share"], fake)
    assert code == 0
    header = out.splitlines()[0]
    assert header.split() == ["#", "LABEL", "CLAIM", "SOURCE", "SPAN"]
    assert "SUPPORTED" in out and "sales increased 12 percent" in out and "1/1 numbers supported" in out
    document, sources, kw = fake.calls[0]
    assert document == "Sales rose 12% in 2025."
    assert sources == [{"kind": "url", "value": "https://x.example"}]
    assert kw["share"] is True and kw["pdfs"] == []


def test_mismatch_fails_by_default_and_fail_on_none_passes(doc):
    assert _run(["check", str(doc), "-s", "https://x"], Fake(_result(mismatch=1)))[0] == 1
    assert _run(["check", str(doc), "-s", "https://x", "--fail-on", "none"], Fake(_result(mismatch=1)))[0] == 0
    assert _run(["check", str(doc), "-s", "https://x"], Fake(_result(unsupported=1)))[0] == 0
    assert _run(["check", str(doc), "-s", "https://x", "--fail-on", "unsupported"], Fake(_result(unsupported=1)))[0] == 1


def test_json_and_markdown_formats(doc):
    code, out, _ = _run(["check", str(doc), "-s", "https://x", "--format", "json", "--fail-on", "none"],
                        Fake(_result(mismatch=1)))
    assert code == 0 and json.loads(out)["summary"]["mismatch"] == 1
    code, out, _ = _run(["check", str(doc), "-s", "https://x", "-f", "markdown", "--fail-on", "none"],
                        Fake(_result(mismatch=1, unsupported=1)))
    assert "| # | Verdict | Claim | Number | Source span |" in out
    assert "Costs \\| fell 3%." in out and "| UNSUPPORTED |" in out and "| — |" in out


def test_stdin_document_and_pdf_source(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    fake = Fake()
    code, _, _ = _run(["check", "-", "--source", str(pdf)], fake, stdin="From stdin: 7 cats.")
    assert code == 0
    document, sources, kw = fake.calls[0]
    assert document == "From stdin: 7 cats." and sources == [] and kw["pdfs"] == [pdf]


def test_api_error_exits_two_with_message(doc):
    code, out, err = _run(["check", str(doc), "-s", "https://x"], Fake(exc=RateLimitError("Come back tomorrow.", 429)))
    assert code == 2 and out == "" and "Come back tomorrow." in err and "429" in err


def test_usage_errors_exit_two(doc, tmp_path, capsys):
    assert _run(["check", str(doc)], Fake())[0] == 2  # no source
    assert _run(["check", str(tmp_path / "nope.md"), "-s", "https://x"], Fake())[0] == 2  # missing doc
    with pytest.raises(SystemExit) as e:
        cli.main(["check", str(doc), "--format", "yaml"], check_fn=Fake())
    assert e.value.code == 2
    assert _run([], Fake())[0] == 2  # no command


def test_api_options_are_passed_through(doc):
    fake = Fake()
    _run(["check", str(doc), "-s", "https://x", "--api-base", "http://localhost:1", "--api-key", "k", "--timeout", "5"], fake)
    kw = fake.calls[0][2]
    assert kw["api_base"] == "http://localhost:1" and kw["api_key"] == "k" and kw["timeout"] == 5


def test_mcp_command_without_mcp_package_is_a_friendly_error(monkeypatch):
    from claimtrace_mcp import mcp_server

    def missing():
        raise mcp_server.MissingMCP("the MCP server needs the 'mcp' package: pip install claimtrace-mcp")

    monkeypatch.setattr(mcp_server, "serve", missing)
    code, _, err = _run(["mcp"], Fake())
    assert code == 2 and "pip install claimtrace-mcp" in err
