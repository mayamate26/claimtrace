"""Score a predictions file against ClaimBench dev cases (stdlib only).

    python3 score.py predictions.jsonl [dev-cases.jsonl]

predictions.jsonl: one {"case_id": ..., "label": "SUPPORTED" | "CONTRADICTED" | ...} per line.
A case with no prediction counts as wrong.
"""
import json
import sys
from pathlib import Path


def load(path):
    return [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]


def score(predictions, cases):
    pred = {p["case_id"]: str(p.get("label", "")).upper() for p in predictions}
    wrong = [c["case_id"] for c in cases if pred.get(c["case_id"]) != c["gold_label"]]
    return {"correct": len(cases) - len(wrong), "total": len(cases), "wrong": wrong}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    cases = load(argv[1] if len(argv) > 1 else Path(__file__).with_name("dev-cases.jsonl"))
    res = score(load(argv[0]), cases)
    print(f"{res['correct']}/{res['total']} correct; wrong: {', '.join(res['wrong']) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
