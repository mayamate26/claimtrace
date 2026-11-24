"""GitHub Action entry point: check the numbers in the docs a pull request changed.

Reads its settings from the environment (set by ``action.yml``):

- ``CT_FILES``: glob(s), newline- or comma-separated (default ``**/*.md``)
- ``CT_SOURCES``: newline-separated URLs / paths; empty means each doc's own URLs are its sources
- ``CT_FAIL_ON``: ``mismatch`` | ``unsupported`` | ``none`` (default ``none``)
- ``CT_SHARE``: ``true`` to save public reports so the comment can link them
- ``CLAIMTRACE_API_KEY``, ``CLAIMTRACE_API_BASE``: passed to the client
- ``GITHUB_TOKEN``, ``GITHUB_REPOSITORY``, ``GITHUB_EVENT_PATH``, ``GITHUB_API_URL``,
  ``GITHUB_BASE_REF``, ``GITHUB_STEP_SUMMARY``, ``GITHUB_WORKSPACE``: from Actions

Writes a markdown summary to the step summary and keeps ONE pull request comment (found by
``MARKER``) up to date. At most ``MAX_FILES`` files per run. Never fails the job on API or
GitHub errors; only ``fail-on`` sets a non-zero exit.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from . import render
from .cli import split_sources
from .client import ClaimTraceError, check

MARKER = "<!-- claimtrace -->"
MAX_FILES = 5
MAX_SOURCES = 3
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", "dist", "build"}
_URL = re.compile(r"https?://[^\s<>()\[\]\"'`]+")


@dataclass
class FileResult:
    path: str
    result: dict | None = None
    error: str = ""
    sources: list = field(default_factory=list)


# --- selecting files ---------------------------------------------------------------------


def glob_regex(pattern: str) -> re.Pattern:
    """A path glob as a regex: ``**/`` any directories (or none), ``*`` within one segment."""
    out, i = [], 0
    pattern = pattern.strip()
    if pattern.startswith("./"):
        pattern = pattern[2:]
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def patterns(files_input: str) -> list[re.Pattern]:
    globs = [g for g in re.split(r"[\n,]", files_input or "") if g.strip()] or ["**/*.md"]
    return [glob_regex(g) for g in globs]


def matches(path: str, pats: list[re.Pattern]) -> bool:
    return any(p.match(path) for p in pats)


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True,
                          timeout=60).stdout


def changed_files(root: Path, event: dict, base_ref: str = "", git=_git) -> list[str] | None:
    """Files changed in the PR (added/modified, not deleted), or None outside a PR / when git can't tell."""
    pr = event.get("pull_request") or {}
    base_sha = (pr.get("base") or {}).get("sha", "")
    base_ref = base_ref or (pr.get("base") or {}).get("ref", "")
    if not (base_sha or base_ref):
        return None
    if base_sha:  # shallow checkouts lack the base commit; fetching it is best effort
        try:
            git(["fetch", "--quiet", "--depth=1", "origin", base_sha], root)
        except (subprocess.SubprocessError, OSError):
            pass
    for base in [b for b in (base_sha, f"origin/{base_ref}" if base_ref else "") if b]:
        for rng in ([f"{base}...HEAD"], [base, "HEAD"]):  # merge-base diff, then a plain one
            try:
                out = git(["diff", "--name-only", "--diff-filter=AM", *rng], root)
            except (subprocess.SubprocessError, OSError):
                continue
            return [line.strip() for line in out.splitlines() if line.strip()]
    return None


def all_files(root: Path, pats: list[re.Pattern]) -> list[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            rel = (Path(dirpath) / name).relative_to(root).as_posix()
            if matches(rel, pats):
                found.append(rel)
    return found


def select_files(root: Path, files_input: str, event: dict, base_ref: str = "", git=_git) -> tuple[list[str], int]:
    """(files to check, how many matching files were left out by the cap)."""
    pats = patterns(files_input)
    changed = changed_files(root, event, base_ref, git)
    if changed is None:
        picked = all_files(root, pats)
    else:
        picked = [f for f in changed if matches(f, pats) and (root / f).is_file()]
    return picked[:MAX_FILES], max(0, len(picked) - MAX_FILES)


# --- sources -----------------------------------------------------------------------------


def urls_in(text: str) -> list[str]:
    seen = []
    for u in _URL.findall(text):
        u = u.rstrip(".,;:!?*_")
        if u not in seen:
            seen.append(u)
    return seen


def sources_for(doc_text: str, sources_input: str, root: Path) -> tuple[list[dict], list[Path]]:
    lines = [s.strip() for s in (sources_input or "").splitlines() if s.strip()]
    if lines:
        resolved = [str(root / s) if not s.lower().startswith(("http://", "https://")) and (root / s).is_file() else s
                    for s in lines]
        return split_sources(resolved[:MAX_SOURCES])
    return [{"kind": "url", "value": u} for u in urls_in(doc_text)[:MAX_SOURCES]], []


# --- running -----------------------------------------------------------------------------


def run_checks(root: Path, files: list[str], sources_input: str, share: bool, check_fn=check) -> list[FileResult]:
    results = []
    for rel in files:
        fr = FileResult(rel)
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
            specs, pdfs = sources_for(text, sources_input, root)
            fr.sources = [s["value"] if s["kind"] == "url" else "(text file)" for s in specs] + [p.name for p in pdfs]
            if not specs and not pdfs:
                fr.error = "no sources: the file links no URLs and no `sources` input was given"
            else:
                fr.result = check_fn(text, specs, share=share, pdfs=pdfs)
        except ClaimTraceError as exc:
            fr.error = str(exc)
        except OSError as exc:
            fr.error = f"could not read: {exc}"
        results.append(fr)
    return results


def _cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def build_body(results: list[FileResult], skipped: int = 0) -> str:
    """The PR comment / step summary: per-file "x/y supported" and report links."""
    lines = [MARKER, "### ClaimTrace: numbers checked against their sources", ""]
    if not results:
        lines.append("No matching documents changed in this pull request.")
    else:
        lines += ["| File | Supported | Mismatch | Unsupported | Report |", "|---|---|---|---|---|"]
        for fr in results:
            if fr.result is None:
                lines.append(f"| `{_cell(fr.path)}` | — | — | — | skipped: {_cell(fr.error)} |")
                continue
            s = fr.result.get("summary") or {}
            link = f"[report]({fr.result['share_url']})" if fr.result.get("share_url") else "—"
            mism = s.get("mismatch", 0)
            lines.append(f"| `{_cell(fr.path)}` | {s.get('supported', 0)}/{s.get('total', 0)} supported | "
                         f"{'**' + str(mism) + '**' if mism else 0} | {s.get('unsupported', 0)} | {link} |")
    for fr in results:
        unchecked = render.not_checked(fr.result) if fr.result else []
        if unchecked:
            lines += ["", f"**Not checked in `{_cell(fr.path)}`:** {_cell(render.coverage_note(fr.result))}"]
            lines += [f"- {_cell(s)}" for s in unchecked]
    if skipped:
        lines += ["", f"_{skipped} more matching file(s) not checked (limit {MAX_FILES} per run)._"]
    lines += ["", "<sub>Checked by [ClaimTrace](https://mayamate.com/claimtrace/). Verdicts are a first pass: "
              "end to end on 31 held-out real government-statistics claims (engine check-v3, 2026-11-24): 16 of 18 correct numbers marked supported, no false mismatches; of 13 wrong numbers, 5 marked mismatch, 5 unsupported, 3 missed. Supported is a first pass, not proof.</sub>"]
    return "\n".join(lines) + "\n"


# --- GitHub ------------------------------------------------------------------------------


def upsert_comment(http: httpx.Client, api: str, repo: str, number: int, body: str) -> str:
    """Update the comment carrying ``MARKER`` or create one. Returns "updated" or "created"."""
    url = f"{api}/repos/{repo}/issues/{number}/comments"
    for page in range(1, 11):
        r = http.get(url, params={"per_page": 100, "page": page})
        r.raise_for_status()
        batch = r.json()
        for c in batch:
            if MARKER in (c.get("body") or ""):
                http.patch(f"{api}/repos/{repo}/issues/comments/{c['id']}", json={"body": body}).raise_for_status()
                return "updated"
        if len(batch) < 100:
            break
    http.post(url, json={"body": body}).raise_for_status()
    return "created"


def github_client(token: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(timeout=30, transport=transport, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "claimtrace-action"})


def _load_event(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    except (OSError, ValueError):
        return {}


def _truthy(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def main(env: dict | None = None, check_fn=check, git=_git, transport: httpx.BaseTransport | None = None,
         stdout=None) -> int:
    env = os.environ if env is None else env
    stdout = stdout or sys.stdout
    root = Path(env.get("GITHUB_WORKSPACE") or ".").resolve()
    event = _load_event(env.get("GITHUB_EVENT_PATH", ""))
    fail_on = (env.get("CT_FAIL_ON") or "none").strip().lower()
    if fail_on not in render.FAIL_ON:
        print(f"::warning::claimtrace: unknown fail-on '{fail_on}', using 'none'", file=stdout)
        fail_on = "none"
    files, skipped = select_files(root, env.get("CT_FILES", ""), event, env.get("GITHUB_BASE_REF", ""), git)
    results = run_checks(root, files, env.get("CT_SOURCES", ""), _truthy(env.get("CT_SHARE", "true")), check_fn)
    body = build_body(results, skipped)
    print(body, file=stdout)
    for fr in results:
        if fr.error:
            print(f"::warning file={fr.path}::claimtrace: {fr.error}", file=stdout)
    summary_path = env.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write(body)
        except OSError as exc:
            print(f"::warning::claimtrace: could not write step summary: {exc}", file=stdout)
    number = (event.get("pull_request") or {}).get("number")
    token, repo = env.get("GITHUB_TOKEN", ""), env.get("GITHUB_REPOSITORY", "")
    if token and repo and number:
        api = (env.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
        try:
            with github_client(token, transport) as http:
                print(f"claimtrace: PR comment {upsert_comment(http, api, repo, int(number), body)}", file=stdout)
        except httpx.HTTPError as exc:
            print(f"::warning::claimtrace: could not post the PR comment ({exc}); "
                  "forked PRs get a read-only token", file=stdout)
    failing = [fr.path for fr in results if fr.result and render.failed(fr.result, fail_on)]
    if failing:
        print(f"::error::claimtrace: fail-on={fail_on} met in: {', '.join(failing)}", file=stdout)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
