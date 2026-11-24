# ClaimBench dev set

Small, public test cases for number checkers. Each case is one claim sentence and the US government
release it is about. A person labelled each claim `SUPPORTED` or `CONTRADICTED` by hand. The claims are
sentences written for the bench. The evidence is the release text. The page with current results is
at <https://mayamate.com/guides/claimbench/>.

There are 19 cases, so treat any score as rough. The held-out set that ClaimTrace is measured on
stays private.

## Files

- `dev-cases.jsonl`: one case per line.
  - `case_id`: unique id, e.g. `d01`
  - `set`: which batch the case came from (`real-v1`, `real-v2`)
  - `claim`: the sentence to check
  - `evidence_file`: path to the evidence text, relative to this folder
  - `gold_label`: `SUPPORTED` or `CONTRADICTED`
  - `kind`: `direct` (the number is printed in the source), `derived` (you have to compute it from
    printed figures) or `wrong-column` (the number is in the source, but not in the column the
    claim describes)
  - `gold_cell` (some cases): where the right number is in the source, written for people
- `evidence/<key>.txt`: the source texts.
- `results-dev.jsonl`: ClaimTrace's results, one case per line: `gold_label`, then `production`
  (the checker the live service runs) and `candidate` (a version under test), each with `label`,
  `correct` and `numbers`, the numbers it pulled from the claim with a verdict for each (`SUPPORTED`,
  `MISMATCH` or `UNSUPPORTED`). A case-level `NOT_IN_EVIDENCE` means "not in source" and counts as wrong.

## Score your checker

Write one JSON line per case:

```json
{"case_id": "d01", "label": "CONTRADICTED"}
```

Then run:

```sh
python3 score.py predictions.jsonl            # uses dev-cases.jsonl next to it
```

It prints `correct/total` and the ids it got wrong. Missing cases count as wrong. Send your predictions
and a line on how you made them to maya@mayamate.com for the leaderboard.
Contact blocks (phone/address lines) are removed from the evidence copies, and footnote labels "Source:" read "Source -"; everything else is the agency text as published.
