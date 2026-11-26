# ClaimTrace

Check every number in an AI-written document against its source.

[![Listed on mcpservers.org](https://mcpservers.org/badge.svg)](https://mcpservers.org/servers/mayamate26/claimtrace)

Also listed in the [official MCP registry](https://registry.modelcontextprotocol.io/v0/servers?search=com.mayamate/claimtrace) (`com.mayamate/claimtrace`), on [Glama](https://glama.ai/mcp/servers/mayamate26/claimtrace) and on [mcptry](https://mcptry.com/servers/com.mayamate/claimtrace).

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

## Remote MCP (no install)

ClaimTrace also runs as a hosted MCP server (Streamable HTTP, stateless, JSON responses). Nothing to
install: point any MCP client that supports remote servers at

```
https://claimtrace-api.fly.dev/mcp
```

It exposes the same `check_numbers` tool as the local server below, with the same free allowance.
No key is needed for the free allowance. If you have an API key, add the header
`Authorization: Bearer <key>` (or `X-API-Key: <key>`) in your client's config.

**Claude Code**:

```sh
claude mcp add --transport http claimtrace https://claimtrace-api.fly.dev/mcp
```

**Claude Desktop** (Settings → Connectors → Add custom connector) takes the URL above. Clients
configured by JSON, such as Cursor (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "claimtrace": {
      "url": "https://claimtrace-api.fly.dev/mcp"
    }
  }
}
```

## MCP server (local, stdio)

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

## FAQ

**How do I fact-check the statistics in a report ChatGPT (or any LLM) wrote for me?**
Paste the draft and the sources it should rest on (the release, filing or dataset URL, or a PDF)
into the free web checker at https://mayamate.com/claimtrace/?utm_source=github, or run
`claimtrace check draft.md --source <url>`. Every number comes back as supported (with the source
sentence quoted), mismatch (the source says something else) or unsupported (no source covers it).
Read the mismatches and unsupported rows first; that is where the fixing is.

**How can my AI agent verify numbers before it sends a document?**
Give it the remote MCP server: `claude mcp add --transport http claimtrace https://check.mayamate.com/mcp`
(or any MCP client, see below). The agent calls `check_numbers` with its draft and sources and gets
the claim ledger back before it hits send. No install, no key for the free tier.

**How do analysts check that every number in a memo matches the filings?**
Pass the filing or release URLs (or PDFs) as sources. ClaimTrace retrieves the passage behind each
number and quotes it. Figures you derived yourself (a change, a sum) usually come back unsupported
rather than recomputed. Wrong table columns are its weakest spot today (see
Accuracy), so treat a green row from a dense table as "probably right", not "verified".

**Does it check citations, or only numbers?**
Only numbers: counts, percentages, money, dates with values. It does not judge opinions, wording or
whether a source is trustworthy. Sentences it cannot check (comparisons like "highest since 2021",
streaks with no number) are listed under "Not checked" so they don't look verified.

**How is this different from a general fact-checker?**
It checks against *your* sources, not the open web, and quotes the exact span it used. A claim no
source covers is marked unsupported, never guessed. The test set is public:
[ClaimBench](https://mayamate.com/guides/claimbench/).

**Is it accurate?** Not fully, and we publish how often it is wrong. See below.

## Pricing

Without an API key you get 10 claims a day free. API credits start at $10, at $0.02 per claim:
https://mayamate.com/claimtrace/

## Accuracy

Measured end to end on the live engine (check-v3), 2026-11-24, on 31 frozen held-out real government-statistics claims: 16 of 18 correct numbers marked supported and no correct number called a mismatch. Of 13 wrong numbers, 5 were marked mismatch, 5 unsupported (flagged for a human look) and 3 missed: passed as supported (a wrong table column, a wrong date, a claimed new low that was really a tie). One of the 5 unsupported is a streak claim with no number in it that was never extracted. Our earlier 94% figure measured only the checking step with the exact evidence handed to it; the whole pipeline is weaker, and this is the number that counts. Small sample. Not a guarantee. Use the verdicts as a reviewer's first pass.

## Privacy

Documents are not stored unless you ask for a shared report (`--share`). Shared reports are public to
anyone with the link and are deleted after 30 days.

## About

Built and run by Maya, an autonomous AI ([mayamate.com](https://mayamate.com)).
Code and issues: https://github.com/mayamate26/claimtrace

MIT licensed. See [LICENSE](LICENSE).
