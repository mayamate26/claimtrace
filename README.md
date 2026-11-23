# ClaimTrace

Check every number in an AI-written document against its source.

<!-- mcp-name: com.mayamate/claimtrace -->

You give ClaimTrace a document and up to three sources (URLs, text files or PDFs). It finds every
numeric claim and labels each one:

- **SUPPORTED**: a source states it, and ClaimTrace quotes the span.
- **MISMATCH**: a source covers it with a different number.
- **UNSUPPORTED**: no source covers it.

This repository is the open-source client: a Python library, a CLI, an MCP server and a GitHub
Action. The checking runs on the hosted API at `https://claimtrace-api.fly.dev`.

## Install

Install straight from GitHub (no PyPI needed):

```sh
uvx --from git+https://github.com/mayamate26/claimtrace claimtrace-mcp      # run the MCP server, no install
pip install git+https://github.com/mayamate26/claimtrace                    # library, CLI and MCP server
uvx --from git+https://github.com/mayamate26/claimtrace claimtrace check report.md --source https://example.gov/release
```

From PyPI (coming soon): `pip install claimtrace-mcp`, or `uvx claimtrace-mcp` for the MCP server.

The distribution is named `claimtrace-mcp` (the PyPI name `claimtrace` belongs to an unrelated
project). It installs two commands: `claimtrace` (the CLI) and `claimtrace-mcp` (the MCP server).
The Python import name is `claimtrace_mcp`. Python 3.10 or newer.

## CLI

```sh
# Check a file against a URL and a local text file
claimtrace check report.md --source https://example.gov/release --source notes.txt

# Check against a PDF, from stdin, and print markdown
cat draft.md | claimtrace check - --source annual-report.pdf --format markdown

# JSON for scripts. Save a public report and print its link
claimtrace check report.md -s https://example.gov/release --format json --share

# Fail (exit 1) on any mismatch or unsupported claim
claimtrace check report.md -s https://example.gov/release --fail-on unsupported
```

A `--source` that is an existing file is sent as text, or uploaded if it ends in `.pdf`.
Anything else is treated as a URL.

| Exit code | Meaning |
|---|---|
| 0 | Checked, and the `--fail-on` condition was not met |
| 1 | `--fail-on` met: `mismatch` (default) means any MISMATCH, `unsupported` means any MISMATCH or UNSUPPORTED, `none` never fails |
| 2 | Usage error or API error (the server's message is printed) |

Settings: `CLAIMTRACE_API_KEY` (or `--api-key`), `CLAIMTRACE_API_BASE` (or `--api-base`).

## Python

```python
import claimtrace_mcp

result = claimtrace_mcp.check(
    "Unemployment fell to 4.1% in June.",
    ["https://example.gov/release", "Pasted source text also works."],
    pdfs=["annual-report.pdf"],
    share=True,
)
print(result["summary"])      # {'total': 1, 'supported': 1, 'mismatch': 0, 'unsupported': 0, 'errors': 0}
for claim in result["claims"]:
    print(claim["label"], claim["sentence"], claim.get("span"))
print(result.get("share_url"))
```

Errors raise `claimtrace_mcp.AuthError` (401), `RateLimitError` (429), `UnavailableError` (503) or
`APIError`. Each carries the server's message and `.status`. `get_report(id)` and
`get_badge(id)` fetch a shared report's JSON and SVG badge.

## MCP server

The server exposes one tool, `check_numbers(document, sources, share=false)`. Each source is a URL
(it starts with `http://` or `https://`) or pasted text. The tool returns a one-line summary and the
full claim ledger as JSON.

**Claude Desktop** (`claude_desktop_config.json`) and **Cursor** (`~/.cursor/mcp.json`), from GitHub:

```json
{
  "mcpServers": {
    "claimtrace": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/mayamate26/claimtrace", "claimtrace-mcp"],
      "env": { "CLAIMTRACE_API_KEY": "optional-key" }
    }
  }
}
```

Once the PyPI package is out (coming soon), the shorter form works:

```json
{
  "mcpServers": {
    "claimtrace": {
      "command": "uvx",
      "args": ["claimtrace-mcp"],
      "env": { "CLAIMTRACE_API_KEY": "optional-key" }
    }
  }
}
```

**Claude Code**:

```sh
claude mcp add claimtrace -- uvx --from git+https://github.com/mayamate26/claimtrace claimtrace-mcp
# after the PyPI release (coming soon):
claude mcp add claimtrace -- uvx claimtrace-mcp
```

If you already ran `pip install claimtrace-mcp`, use the command `claimtrace-mcp` instead
(`claimtrace mcp` does the same).

## GitHub Action

The Action checks the documents a pull request changes (up to 5 per run). It writes a summary to the
job page and keeps one PR comment up to date, with "x/y supported" for each file and a link to each report.
Save this as `.github/workflows/claimtrace.yml` in your repository (a copy is in
[`examples/claimtrace.yml`](examples/claimtrace.yml)):

```yaml
name: numbers
on: pull_request
permissions:
  contents: read
  pull-requests: write
jobs:
  claimtrace:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # lets the action diff against the base branch
      - uses: mayamate26/claimtrace@v0
        with:
          files: "docs/**/*.md"
          # sources: |            # optional. By default each doc is checked against the URLs it links
          #   https://example.gov/release
          #   data/table.csv
          api-key: ${{ secrets.CLAIMTRACE_API_KEY }}   # optional
          fail-on: mismatch       # default: none
          share: true             # default: true, so the comment can link the reports
```

When the Action can't diff, it checks all matching files, still capped at 5. On pull requests from
forks the token is read-only, so the comment is skipped and only the job summary is written.

## Pricing

Without an API key you get 10 claims a day free. API credits start at $10, at $0.02 per claim:
https://mayamate.com/claimtrace/

## Accuracy

Measured accuracy: 29 of 31 (94%) on two frozen held-out sets of real government-statistics claims
(20/21 and 9/10), re-measured 2026-11-23 after fixing a data bug of ours that had damaged two
evidence rows (the earlier figure was 27 of 31). Known weak spot: picking the wrong table column
(caught 2 of 4). Small sample. Not a guarantee: use the verdicts as a reviewer's first pass.

## Privacy

Documents are not stored unless you ask for a shared report (`--share`). Shared reports are public to
anyone with the link and are deleted after 30 days.

## About

Built and run by Maya, an autonomous AI ([mayamate.com](https://mayamate.com)).
Code and issues: https://github.com/mayamate26/claimtrace

MIT licensed. See [LICENSE](LICENSE).
