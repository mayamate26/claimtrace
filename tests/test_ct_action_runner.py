"""The GitHub Action runner: file selection, sources, comment body, one-comment upsert."""

import io
import json
import subprocess

import httpx
import pytest

from claimtrace_mcp import action_runner as ar
from claimtrace_mcp.client import RateLimitError


def _res(supported, total, mismatch=0, unsupported=0, share_url=None):
    r = {"claims": [], "notices": [], "summary": {"total": total, "supported": supported, "mismatch": mismatch,
                                                  "unsupported": unsupported, "errors": 0}}
    if share_url:
        r["share_url"] = share_url
    return r


# --- globs and files ---------------------------------------------------------------------


@pytest.mark.parametrize("glob,path,ok", [
    ("**/*.md", "README.md", True), ("**/*.md", "docs/a/b.md", True), ("**/*.md", "docs/a.txt", False),
    ("docs/*.md", "docs/a.md", True), ("docs/*.md", "docs/x/a.md", False), ("docs/**", "docs/x/a.md", True),
    ("./docs/?.md", "docs/a.md", True), ("*.md", "docs/a.md", False),
])
def test_glob_regex(glob, path, ok):
    assert bool(ar.glob_regex(glob).match(path)) is ok


def test_patterns_split_on_newlines_and_commas():
    pats = ar.patterns("docs/*.md, *.txt\n")
    assert ar.matches("docs/a.md", pats) and ar.matches("b.txt", pats) and not ar.matches("c.rst", pats)
    assert ar.matches("deep/x.md", ar.patterns(""))  # default **/*.md


def _tree(tmp_path):
    for rel in ["README.md", "docs/a.md", "docs/b.md", "docs/c.txt", "node_modules/x.md", "__pycache__/y.md"]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{rel}: 5 widgets, see https://src.example/{rel}.")
    return tmp_path


PR_EVENT = {"pull_request": {"number": 7, "base": {"sha": "basesha", "ref": "main"}}}


def test_select_changed_files_only(tmp_path):
    root = _tree(tmp_path)
    calls = []

    def git(args, cwd):
        calls.append(args)
        if args[0] == "fetch":
            return ""
        return "docs/a.md\ndocs/c.txt\ndocs/gone.md\n"

    files, skipped = ar.select_files(root, "**/*.md", PR_EVENT, git=git)
    assert files == ["docs/a.md"] and skipped == 0
    assert ["diff", "--name-only", "--diff-filter=AM", "basesha...HEAD"] in calls


def test_select_falls_back_to_all_files_when_git_fails_or_no_pr(tmp_path):
    root = _tree(tmp_path)

    def broken(args, cwd):
        raise subprocess.CalledProcessError(128, "git")

    assert ar.select_files(root, "**/*.md", PR_EVENT, git=broken) == (["README.md", "docs/a.md", "docs/b.md"], 0)
    assert ar.select_files(root, "**/*.md", {}, git=broken)[0] == ["README.md", "docs/a.md", "docs/b.md"]


def test_select_caps_at_five(tmp_path):
    for i in range(8):
        (tmp_path / f"f{i}.md").write_text("x")
    files, skipped = ar.select_files(tmp_path, "*.md", {})
    assert len(files) == ar.MAX_FILES == 5 and skipped == 3


# --- sources -----------------------------------------------------------------------------


def test_urls_in_doc_are_default_sources_max_three(tmp_path):
    text = ("See [a](https://a.example/x). Also https://b.example/y, https://a.example/x again, "
            "<https://c.example/z> and https://d.example/w.")
    assert ar.urls_in(text) == ["https://a.example/x", "https://b.example/y", "https://c.example/z", "https://d.example/w"]
    specs, pdfs = ar.sources_for(text, "", tmp_path)
    assert [s["value"] for s in specs] == ["https://a.example/x", "https://b.example/y", "https://c.example/z"]
    assert pdfs == []


def test_sources_input_paths_resolve_against_the_workspace(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "t.csv").write_text("year,value\n2025,5")
    (tmp_path / "data" / "r.pdf").write_bytes(b"%PDF")
    specs, pdfs = ar.sources_for("doc https://ignored.example", "https://s.example\ndata/t.csv\ndata/r.pdf\n", tmp_path)
    assert specs == [{"kind": "url", "value": "https://s.example"}, {"kind": "text", "value": "year,value\n2025,5"}]
    assert pdfs == [tmp_path / "data" / "r.pdf"]


# --- body --------------------------------------------------------------------------------


def test_build_body_per_file_lines_and_links():
    results = [ar.FileResult("docs/a.md", _res(3, 4, mismatch=1, share_url="https://claimtrace-api.fly.dev/r/abc123")),
               ar.FileResult("docs/b|c.md", _res(2, 2)),
               ar.FileResult("docs/d.md", error="no sources: the file links no URLs")]
    body = ar.build_body(results, skipped=2)
    assert body.startswith(ar.MARKER + "\n")
    assert "| `docs/a.md` | 3/4 supported | **1** | 0 | [report](https://claimtrace-api.fly.dev/r/abc123) |" in body
    assert "| `docs/b\\|c.md` | 2/2 supported | 0 | 0 | — |" in body
    assert "| `docs/d.md` | — | — | — | skipped: no sources: the file links no URLs |" in body
    assert "2 more matching file(s) not checked (limit 5 per run)" in body


def test_build_body_with_nothing_to_check():
    assert "No matching documents changed" in ar.build_body([])


# --- the GitHub comment ------------------------------------------------------------------


class FakeGitHub:
    def __init__(self, comments=None, fail=None):
        self.comments = list(comments or [])
        self.requests = []
        self.fail = fail

    def __call__(self, request: httpx.Request):
        self.requests.append(request)
        assert request.headers["authorization"] == "Bearer tok"
        if self.fail:
            return httpx.Response(self.fail, json={"message": "Resource not accessible by integration"})
        path = request.url.path
        if request.method == "GET" and path == "/repos/o/r/issues/7/comments":
            page = int(request.url.params.get("page", 1))
            per = int(request.url.params.get("per_page", 30))
            return httpx.Response(200, json=self.comments[(page - 1) * per: page * per])
        if request.method == "POST" and path == "/repos/o/r/issues/7/comments":
            c = {"id": 999, "body": json.loads(request.content)["body"]}
            self.comments.append(c)
            return httpx.Response(201, json=c)
        if request.method == "PATCH" and path.startswith("/repos/o/r/issues/comments/"):
            cid = int(path.rsplit("/", 1)[1])
            for c in self.comments:
                if c["id"] == cid:
                    c["body"] = json.loads(request.content)["body"]
                    return httpx.Response(200, json=c)
        return httpx.Response(404, json={"message": "Not Found"})


def _gh(fake):
    return ar.github_client("tok", httpx.MockTransport(fake))


def test_upsert_creates_then_updates_one_comment():
    fake = FakeGitHub([{"id": 1, "body": "unrelated"}])
    with _gh(fake) as http:
        assert ar.upsert_comment(http, "https://api.github.com", "o/r", 7, ar.MARKER + "\nfirst") == "created"
        assert ar.upsert_comment(http, "https://api.github.com", "o/r", 7, ar.MARKER + "\nsecond") == "updated"
    assert [c["body"] for c in fake.comments] == ["unrelated", ar.MARKER + "\nsecond"]


def test_upsert_finds_the_marker_on_a_later_page():
    comments = [{"id": i, "body": f"c{i}"} for i in range(150)] + [{"id": 500, "body": f"old {ar.MARKER}"}]
    fake = FakeGitHub(comments)
    with _gh(fake) as http:
        assert ar.upsert_comment(http, "https://api.github.com", "o/r", 7, "new " + ar.MARKER) == "updated"
    assert fake.comments[-1]["body"] == "new " + ar.MARKER
    assert not [r for r in fake.requests if r.method == "POST"]


# --- end to end --------------------------------------------------------------------------


def _env(tmp_path, **extra):
    event = tmp_path / "event.json"
    event.write_text(json.dumps(PR_EVENT))
    summary = tmp_path / "summary.md"
    env = {"GITHUB_WORKSPACE": str(tmp_path / "ws"), "GITHUB_EVENT_PATH": str(event), "GITHUB_STEP_SUMMARY": str(summary),
           "GITHUB_TOKEN": "tok", "GITHUB_REPOSITORY": "o/r", "GITHUB_API_URL": "https://api.github.com",
           "CT_FILES": "**/*.md", "CT_SOURCES": "", "CT_FAIL_ON": "none", "CT_SHARE": "true"}
    env.update(extra)
    return env, summary


def _ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "docs").mkdir(parents=True)
    (ws / "docs" / "a.md").write_text("Output grew 3% (https://stats.example/out).")
    (ws / "docs" / "b.md").write_text("No links here, 4 items.")
    return ws


def _git_changed(args, cwd):
    return "" if args[0] == "fetch" else "docs/a.md\ndocs/b.md\n"


def test_main_end_to_end_posts_one_comment_and_writes_summary(tmp_path):
    _ws(tmp_path)
    env, summary = _env(tmp_path)
    calls = []

    def check_fn(text, specs, share=False, pdfs=None):
        calls.append((text, specs, share))
        return _res(1, 2, mismatch=1, share_url="https://claimtrace-api.fly.dev/r/xyz789")

    fake = FakeGitHub()
    out = io.StringIO()
    code = ar.main(env, check_fn=check_fn, git=_git_changed, transport=httpx.MockTransport(fake), stdout=out)
    assert code == 0  # fail-on none
    assert calls == [("Output grew 3% (https://stats.example/out).", [{"kind": "url", "value": "https://stats.example/out"}], True)]
    text = summary.read_text()
    assert "1/2 supported" in text and "r/xyz789" in text and "`docs/b.md`" in text and "skipped: no sources" in text
    assert len(fake.comments) == 1 and fake.comments[0]["body"].startswith(ar.MARKER)
    assert "::warning file=docs/b.md::" in out.getvalue()
    # a second run updates the same comment, never adds another
    ar.main(env, check_fn=check_fn, git=_git_changed, transport=httpx.MockTransport(fake), stdout=io.StringIO())
    assert len(fake.comments) == 1


def test_main_fail_on_mismatch_exits_one(tmp_path):
    _ws(tmp_path)
    env, _ = _env(tmp_path, CT_FAIL_ON="mismatch", GITHUB_TOKEN="")
    out = io.StringIO()
    code = ar.main(env, check_fn=lambda *a, **k: _res(1, 2, mismatch=1), git=_git_changed, stdout=out)
    assert code == 1 and "::error::" in out.getvalue() and "docs/a.md" in out.getvalue()


def test_main_api_and_github_errors_do_not_fail_the_job(tmp_path):
    _ws(tmp_path)
    env, summary = _env(tmp_path, CT_FAIL_ON="mismatch")

    def limited(*a, **k):
        raise RateLimitError("You've used your free 10 claims for today.", 429)

    out = io.StringIO()
    code = ar.main(env, check_fn=limited, git=_git_changed, transport=httpx.MockTransport(FakeGitHub(fail=403)), stdout=out)
    assert code == 0
    assert "free 10 claims" in summary.read_text()
    assert "could not post the PR comment" in out.getvalue()


def test_main_outside_a_pr_checks_all_files_and_posts_nothing(tmp_path):
    _ws(tmp_path)
    env, summary = _env(tmp_path)
    (tmp_path / "event.json").write_text("{}")
    fake = FakeGitHub()
    seen = []
    ar.main(env, check_fn=lambda t, s, **k: seen.append(t) or _res(1, 1), git=_git_changed,
            transport=httpx.MockTransport(fake), stdout=io.StringIO())
    assert seen == ["Output grew 3% (https://stats.example/out)."]
    assert fake.requests == [] and "`docs/a.md`" in summary.read_text()
