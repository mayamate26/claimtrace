"""Stdio MCP server exposing ``check_numbers``.

Run with ``claimtrace-mcp`` (or ``uvx claimtrace-mcp``, or ``claimtrace mcp``). ``mcp`` is a required
dependency of the ``claimtrace-mcp`` distribution, but it is imported lazily: the tool logic lives in
:func:`check_numbers` and works without it; only :func:`serve` imports it.
"""

from __future__ import annotations

import sys
from typing import Annotated, Any

try:  # pydantic ships with mcp; the tool logic itself does not need it
    from pydantic import Field
except ImportError:  # pragma: no cover
    def Field(**_kw):  # noqa: N802
        return None

from . import render
from .client import ClaimTraceError, check, source_spec

INSTRUCTIONS = ("ClaimTrace checks every number in a document against the sources you give it. Each claim "
                "comes back SUPPORTED, MISMATCH or UNSUPPORTED with the source span that decides it. "
                "Accuracy: 94% (29/31) on held-out real claims for engine check-v2 (current check-v3 re-measure pending); weak on wrong-table-column cases. "
                "Not a guarantee: treat verdicts as a reviewer's first pass.")


DOC_DESC = ("The text whose numbers you want checked (an AI-written draft, memo, investor update, "
            "article). Plain text or markdown. Every numeric claim in it is extracted and checked.")
SOURCES_DESC = ("1 to 3 sources the numbers should come from. Each item is either a public http(s) URL "
                "(HTML or PDF, fetched by the server) or the source text pasted directly.")
SHARE_DESC = ("If true, also publish the claim ledger as a public report page and return its link "
              "(kept 30 days). Default false: nothing is stored.")


class MissingMCP(RuntimeError):
    pass


def check_numbers(document: str, sources: list[str], share: bool = False, check_fn=check) -> dict:
    """Check every number in ``document`` against ``sources``.

    Each source is a URL (if it starts with http:// or https://) or pasted source text; at most 3.
    Returns ``{"summary": "<one line>", "ledger": {claims, summary, notices, ...}}``; each claim
    has ``label`` (SUPPORTED / MISMATCH / UNSUPPORTED / ERROR), ``sentence``, ``number``, ``span``
    and ``note``. With ``share`` the result includes a public report link (kept 30 days).
    """
    if not isinstance(sources, list) or not [s for s in sources if str(s).strip()]:
        raise ValueError("Give at least one source: a URL or pasted source text.")
    specs = [source_spec(str(s)) for s in sources if str(s).strip()]
    try:
        result = check_fn(document, specs, share=share)
    except ClaimTraceError as exc:
        raise RuntimeError(f"ClaimTrace API error: {exc}") from exc
    return {"summary": render.summary_line(result), "ledger": result}


def _server_class():
    try:
        from mcp.server.mcpserver import MCPServer  # mcp >= 2

        return MCPServer
    except ImportError:
        pass
    try:
        from mcp.server.fastmcp import FastMCP  # mcp 1.x

        return FastMCP
    except ImportError as exc:
        raise MissingMCP("the MCP server needs the 'mcp' package: pip install claimtrace-mcp "
                         "(or run it with: uvx claimtrace-mcp)") from exc


def build_server():
    server = _server_class()("claimtrace", instructions=INSTRUCTIONS)

    try:
        from mcp.types import ToolAnnotations
    except ImportError:  # pragma: no cover - very old mcp
        ToolAnnotations = None
    # Honest hints: share=true publishes a report page (not read-only); URLs are fetched (open world).
    hints = dict(title="Check numbers against sources", readOnlyHint=False, destructiveHint=False,
                 idempotentHint=False, openWorldHint=True)
    kw = {"annotations": ToolAnnotations(**hints)} if ToolAnnotations else {}

    @server.tool(name="check_numbers", **kw)
    def _check_numbers(
        document: Annotated[str, Field(description=DOC_DESC)],
        sources: Annotated[list[str], Field(description=SOURCES_DESC, min_length=1, max_length=3)],
        share: Annotated[bool, Field(description=SHARE_DESC)] = False,
    ) -> dict[str, Any]:
        """Check every number in an AI-written document against its sources. Each source is a URL
        (http:// or https://) or pasted source text; at most 3. Returns a one-line summary and the
        claim ledger: each numeric claim labelled SUPPORTED, MISMATCH or UNSUPPORTED with the
        source span. Set share=true for a public report link (kept 30 days)."""
        return check_numbers(document, sources, share)

    return server


def serve() -> None:
    build_server().run()


def main() -> int:
    """Entry point of the ``claimtrace-mcp`` console script: start the stdio MCP server."""
    try:
        serve()
    except MissingMCP as exc:
        print(f"claimtrace-mcp: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
