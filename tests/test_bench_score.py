"""bench/score.py: scores a predictions jsonl against dev-cases.jsonl."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("claimbench_score", ROOT / "bench" / "score.py")
score_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(score_mod)


def _jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_score_counts_right_wrong_and_missing(tmp_path, capsys):
    cases = tmp_path / "dev-cases.jsonl"
    preds = tmp_path / "preds.jsonl"
    _jsonl(cases, [{"case_id": "a", "gold_label": "SUPPORTED"},
                   {"case_id": "b", "gold_label": "CONTRADICTED"},
                   {"case_id": "c", "gold_label": "SUPPORTED"}])
    _jsonl(preds, [{"case_id": "a", "label": "supported"}, {"case_id": "b", "label": "SUPPORTED"}])
    assert score_mod.main([str(preds), str(cases)]) == 0
    assert capsys.readouterr().out.strip() == "1/3 correct; wrong: b, c"


def test_score_without_arguments_prints_usage():
    assert score_mod.main([]) == 2
