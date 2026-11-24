"""Coverage disclosure from the server ("not_checked", "coverage_note") in every client output,
and tolerance of older servers that do not send it."""

import io

from claimtrace_mcp import action_runner as ar
from claimtrace_mcp import cli, mcp_server, render

NOTE = ("2 comparison/streak claims found, not checked: ClaimTrace verifies stated numbers against the "
        "source, not claims about a whole series. Check these by hand.")
REASON = "comparison over a series (highest/lowest/since/streak) - not checked"
OLD = {"claims": [], "notices": [], "summary": {"total": 1, "supported": 1, "mismatch": 0, "unsupported": 0, "errors": 0}}
NEW = {**OLD, "coverage_note": NOTE, "not_checked": [
    {"sentence": "The jobless rate fell to a new 2026 low of 4.1%.", "reason": REASON},
    {"sentence": "Payrolls have | increased every month since June.", "reason": REASON}]}


def _cli(result, *extra, tmp_path):
    doc = tmp_path / "d.md"
    doc.write_text("x")
    out = io.StringIO()
    cli.main(["check", str(doc), "-s", "https://x", *extra], check_fn=lambda *a, **k: result,
             stdout=out, stderr=io.StringIO())
    return out.getvalue()


def test_render_helpers():
    assert render.not_checked(OLD) == [] and render.coverage_note(OLD) == ""
    assert render.not_checked({**OLD, "not_checked": "junk"}) == []
    assert render.not_checked(NEW)[0] == "The jobless rate fell to a new 2026 low of 4.1%."
    assert render.coverage_note(NEW) == NOTE
    no_note = {**NEW, "coverage_note": ""}
    assert "Check these by hand" in render.coverage_note(no_note)


def test_cli_table_shows_note_and_sentences(tmp_path):
    out = _cli(NEW, tmp_path=tmp_path)
    assert f"NOT CHECKED: {NOTE}" in out
    assert "  - The jobless rate fell to a new 2026 low of 4.1%." in out
    assert "  - Payrolls have | increased every month since June." in out
    assert "NOT CHECKED" not in _cli(OLD, tmp_path=tmp_path)


def test_cli_markdown_shows_note_and_sentences(tmp_path):
    out = _cli(NEW, "-f", "markdown", tmp_path=tmp_path)
    assert f"**Not checked.** {NOTE}" in out
    assert "- Payrolls have \\| increased every month since June." in out
    assert "Not checked" not in _cli(OLD, "-f", "markdown", tmp_path=tmp_path)


def test_stdio_mcp_result_carries_coverage():
    out = mcp_server.check_numbers("d", ["s"], check_fn=lambda *a, **k: NEW)
    assert out["coverage_note"] == NOTE
    assert out["not_checked"] == [u["sentence"] for u in NEW["not_checked"]]
    old = mcp_server.check_numbers("d", ["s"], check_fn=lambda *a, **k: OLD)
    assert set(old) == {"summary", "ledger"}


def test_action_comment_lists_not_checked_per_file():
    body = ar.build_body([ar.FileResult("docs/a.md", NEW), ar.FileResult("docs/b.md", OLD),
                          ar.FileResult("docs/c.md", error="no sources")])
    assert f"**Not checked in `docs/a.md`:** {NOTE}" in body
    assert "- The jobless rate fell to a new 2026 low of 4.1%." in body
    assert "docs/b.md`:**" not in body and "docs/c.md`:**" not in body
    assert "Not checked in" not in ar.build_body([ar.FileResult("docs/b.md", OLD)])
