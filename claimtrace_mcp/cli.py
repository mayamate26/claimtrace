"""``claimtrace`` command line.

    claimtrace check report.md --source https://example.gov/release --source table.csv
    cat draft.md | claimtrace check - --source notes.txt --format markdown
    claimtrace mcp

Exit codes: 0 ok, 1 the ``--fail-on`` condition was met, 2 usage or API error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, render
from .client import ClaimTraceError, check

EXIT_OK, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


def classify_source(arg: str) -> tuple[str, object]:
    """``("pdf", Path)`` for an existing ``.pdf`` file, ``("text", contents)`` for any other existing
    file, otherwise ``("url", arg)``."""
    p = Path(arg).expanduser()
    try:
        is_file = p.is_file()
    except OSError:
        is_file = False
    if is_file:
        if p.suffix.lower() == ".pdf":
            return "pdf", p
        return "text", p.read_text(encoding="utf-8", errors="replace")
    return "url", arg.strip()


def split_sources(args: list[str]) -> tuple[list[dict], list[Path]]:
    specs, pdfs = [], []
    for a in args:
        kind, value = classify_source(a)
        if kind == "pdf":
            pdfs.append(value)
        else:
            specs.append({"kind": kind, "value": value})
    return specs, pdfs


def read_document(arg: str, stdin=None) -> str:
    if arg == "-":
        return (stdin or sys.stdin).read()
    return Path(arg).expanduser().read_text(encoding="utf-8", errors="replace")


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse already exits 2; keep it explicit
        self.print_usage(sys.stderr)
        self.exit(EXIT_ERROR, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="claimtrace", description="Check every number in an AI-written document against its source.")
    p.add_argument("--version", action="version", version=f"claimtrace {__version__}")
    sub = p.add_subparsers(dest="command", parser_class=_Parser)
    c = sub.add_parser("check", help="check a document's numbers against sources")
    c.add_argument("document", metavar="DOC", help="document file, or '-' for stdin")
    c.add_argument("--source", "-s", action="append", default=[], metavar="URL_OR_FILE",
                   help="a source URL, a text file, or a .pdf file (repeatable, at most 3)")
    c.add_argument("--share", action="store_true", help="save a public report (deleted after 30 days) and print its link")
    c.add_argument("--format", "-f", choices=("table", "json", "markdown"), default="table")
    c.add_argument("--fail-on", choices=render.FAIL_ON, default="mismatch",
                   help="exit 1 on any mismatch (default), any mismatch or unsupported claim, or never")
    c.add_argument("--api-base", default=None, help="API base URL (env CLAIMTRACE_API_BASE)")
    c.add_argument("--api-key", default=None, help="API key (env CLAIMTRACE_API_KEY)")
    c.add_argument("--timeout", type=float, default=180)
    sub.add_parser("mcp", help="run the stdio MCP server (same as the claimtrace-mcp command)")
    return p


def run_check(ns, check_fn=check, stdout=None, stderr=None, stdin=None) -> int:
    stdout, stderr = stdout or sys.stdout, stderr or sys.stderr
    try:
        document = read_document(ns.document, stdin)
        specs, pdfs = split_sources(ns.source)
    except OSError as exc:
        print(f"claimtrace: {exc}", file=stderr)
        return EXIT_ERROR
    if not specs and not pdfs:
        print("claimtrace: add at least one --source (URL, text file or PDF)", file=stderr)
        return EXIT_ERROR
    try:
        result = check_fn(document, specs, share=ns.share, pdfs=pdfs, api_base=ns.api_base,
                          api_key=ns.api_key, timeout=ns.timeout)
    except ClaimTraceError as exc:
        print(f"claimtrace: {exc}", file=stderr)
        return EXIT_ERROR
    if ns.format == "json":
        print(render.as_json(result), file=stdout)
    elif ns.format == "markdown":
        print(render.markdown(result), file=stdout)
    else:
        print(render.table(result), file=stdout)
    return EXIT_FAIL if render.failed(result, ns.fail_on) else EXIT_OK


def main(argv: list[str] | None = None, check_fn=check, stdout=None, stderr=None, stdin=None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    if ns.command == "check":
        return run_check(ns, check_fn, stdout, stderr, stdin)
    if ns.command == "mcp":
        from .mcp_server import MissingMCP, serve

        try:
            serve()
        except MissingMCP as exc:
            print(f"claimtrace: {exc}", file=stderr or sys.stderr)
            return EXIT_ERROR
        return EXIT_OK
    parser.print_help(stderr or sys.stderr)
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
