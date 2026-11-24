"""Turn an API result into a summary line, a terminal table or markdown."""

from __future__ import annotations

import json

FAIL_ON = ("mismatch", "unsupported", "none")


def summary_line(result: dict) -> str:
    s = result.get("summary") or {}
    line = (f"{s.get('supported', 0)}/{s.get('total', 0)} numbers supported, "
            f"{s.get('mismatch', 0)} mismatch, {s.get('unsupported', 0)} unsupported")
    if s.get("errors"):
        line += f", {s['errors']} unchecked"
    if result.get("share_url"):
        line += f". Report: {result['share_url']}"
    return line


def failed(result: dict, fail_on: str) -> bool:
    """``mismatch``: any MISMATCH. ``unsupported``: any MISMATCH or UNSUPPORTED. ``none``: never."""
    s = result.get("summary") or {}
    if fail_on == "mismatch":
        return bool(s.get("mismatch"))
    if fail_on == "unsupported":
        return bool(s.get("mismatch") or s.get("unsupported"))
    return False


def _short(text, width: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= width else t[: width - 1] + "…"


def not_checked(result: dict) -> list[str]:
    """Sentences the server reported as not checked (comparisons over a series); [] from older servers."""
    items = result.get("not_checked") or []
    if not isinstance(items, list):
        return []
    return [" ".join(str(u.get("sentence", "")).split()) for u in items if isinstance(u, dict) and u.get("sentence")]


def coverage_note(result: dict) -> str:
    """The server's coverage note, or a generic one if it sent sentences without a note; "" when none."""
    if not not_checked(result):
        return ""
    return " ".join(str(result.get("coverage_note") or "").split()) or (
        "Comparison/streak claims found, not checked. Check these by hand.")


def table(result: dict, sentence_width: int = 60, span_width: int = 50) -> str:
    claims = result.get("claims") or []
    rows = [("#", "LABEL", "CLAIM", "SOURCE SPAN")]
    for i, c in enumerate(claims, 1):
        rows.append((str(i), str(c.get("label", "")), _short(c.get("sentence"), sentence_width),
                     _short(c.get("span"), span_width) or "-"))
    widths = [max(len(r[k]) for r in rows) for k in range(4)]
    lines = ["  ".join(cell.ljust(widths[k]) for k, cell in enumerate(r)).rstrip() for r in rows]
    if not claims:
        lines.append("(no numeric claims checked)")
    lines += ["", summary_line(result)]
    lines += [f"note: {n}" for n in result.get("notices") or []]
    unchecked = not_checked(result)
    if unchecked:
        lines += ["", f"NOT CHECKED: {coverage_note(result)}"]
        lines += [f"  - {s}" for s in unchecked]
    return "\n".join(lines)


def _md_cell(text) -> str:
    return " ".join(str(text or "").split()).replace("|", "\\|")


def markdown(result: dict) -> str:
    out = [f"**{summary_line(result)}**", "", "| # | Verdict | Claim | Number | Source span |", "|---|---|---|---|---|"]
    for i, c in enumerate(result.get("claims") or [], 1):
        span = _md_cell(c.get("span"))
        out.append(f"| {i} | {_md_cell(c.get('label'))} | {_md_cell(c.get('sentence'))} | "
                   f"{_md_cell(c.get('number'))} | {'“' + span + '”' if span else '—'} |")
    for n in result.get("notices") or []:
        out.append(f"\n_{_md_cell(n)}_")
    unchecked = not_checked(result)
    if unchecked:
        out.append(f"\n**Not checked.** {_md_cell(coverage_note(result))}")
        out += [f"- {_md_cell(s)}" for s in unchecked]
    return "\n".join(out)


def as_json(result: dict) -> str:
    return json.dumps(result, indent=2, ensure_ascii=False)
