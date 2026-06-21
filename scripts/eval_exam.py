#!/usr/bin/env python3
"""Exam-solving evaluation -> JSON report (Phase 3, 案12).

Runs the offline pipeline (layout -> subject -> solver -> HUD view) over a set
of sample questions and reports quality metrics per solver so cloud vs local
adapters can be compared on the SAME inputs once they are registered.

Two input modes:
  1. --samples DIR : read *.json files, each:
       {"ocr_text": str, "choices": [..]?, "subject": str?, "expected_answer": str?}
     (See data/exam_samples/ for clearly-generic, synthetic practice items —
      no copyrighted exam content is shipped.)
  2. --synthetic N : generate N synthetic question-like samples.

Metrics (per solver, averaged over samples):
  - question_extraction_rate : a question unit (no/body) was parsed,
  - subject_detection_rate   : a subject was inferred,
  - answer_rate              : the solver produced a non-empty answer,
  - hud_within_3_lines_rate  : the staged HUD view stayed <= 3 lines,
  - answer_accuracy          : exact-ish match vs expected_answer (only over
                               samples that provide one; null otherwise).

Output: JSON (stdout or --out FILE) stamped with version_info(). No network.

Examples:
  python scripts/eval_exam.py --synthetic 5 --out /tmp/exam_eval.json
  python scripts/eval_exam.py --samples data/exam_samples
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# allow running as a plain script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.glasses_view import build_glasses_view  # noqa: E402
from app.layout import parse_layout, primary_question  # noqa: E402
from app.solvers import Question, get_solver  # noqa: E402
from app.subjects import detect_subject  # noqa: E402
from app.version import version_info  # noqa: E402


def _answer_matches(expected: str | None, answer: str) -> bool:
    if not expected:
        return False
    exp = expected.strip().lower()
    ans = (answer or "").strip().lower()
    if not exp or not ans:
        return False
    label = ans.split(":", 1)[0].strip()
    return exp == label or exp in ans


def _eval_one(sample: dict, solver_name: str) -> dict:
    ocr_text = sample.get("ocr_text", "")
    parsed = parse_layout(ocr_text)
    unit = primary_question(parsed)
    subject, _ = detect_subject(ocr_text)

    body = sample.get("body_text") or (unit.body_text if unit else ocr_text)
    choices = sample.get("choices") or (unit.choices if unit else [])
    question = Question(
        question_no=unit.question_no if unit else None,
        body_text=body,
        choices=choices,
        subject=subject,
    )
    result = get_solver(solver_name).solve(question=question)
    view = build_glasses_view(result)

    expected = sample.get("expected_answer")
    return {
        "question_extracted": bool(unit and (unit.question_no or unit.body_text)),
        "subject_detected": bool(subject),
        "answer_produced": bool((result.answer or "").strip()),
        "hud_within_3_lines": len(view["lines"]) <= 3,
        "has_expected": expected is not None,
        "answer_correct": _answer_matches(expected, result.answer),
        "answer": result.answer,
        "subject": subject,
    }


def _aggregate(per_sample: list[dict]) -> dict:
    n = len(per_sample)
    if n == 0:
        return {}
    expected_rows = [r for r in per_sample if r["has_expected"]]

    def rate(key: str) -> float:
        return round(sum(int(r[key]) for r in per_sample) / n, 4)

    accuracy = (
        round(sum(int(r["answer_correct"]) for r in expected_rows) / len(expected_rows), 4)
        if expected_rows
        else None
    )
    return {
        "sample_count": n,
        "question_extraction_rate": rate("question_extracted"),
        "subject_detection_rate": rate("subject_detected"),
        "answer_rate": rate("answer_produced"),
        "hud_within_3_lines_rate": rate("hud_within_3_lines"),
        "answer_accuracy": accuracy,
        "scored_against_expected": len(expected_rows),
    }


def run_eval(samples: list[dict], solver_names: list[str]) -> dict:
    """Evaluate each solver over `samples`; return a metrics report dict."""
    solvers_report = {}
    for name in solver_names:
        per_sample = [_eval_one(s, name) for s in samples]
        solvers_report[name] = {
            "metrics": _aggregate(per_sample),
            "results": per_sample,
        }
    return {
        "report_kind": "rokid-exam-eval",
        "versions": version_info(),
        "solvers": solver_names,
        "by_solver": solvers_report,
    }


def _load_samples(directory: str) -> list[dict]:
    samples = []
    for path in sorted(Path(directory).glob("*.json")):
        samples.append(json.loads(path.read_text(encoding="utf-8")))
    return samples


def _synthetic(n: int) -> list[dict]:
    subjects = ["数学", "英語", "物理", "化学", "歴史"]
    media = ["", "図1を参照", "次のグラフ", "下の表より"]
    samples = []
    for i in range(n):
        subj_cue = subjects[i % len(subjects)]
        extra = media[i % len(media)]
        ocr = f"問{i + 1} {subj_cue}の問題 {extra}\n① 選択肢A\n② 選択肢B\n③ 選択肢C\n④ 選択肢D"
        samples.append(
            {"ocr_text": ocr, "choices": ["選択肢A", "選択肢B", "選択肢C", "選択肢D"]}
        )
    return samples


def main() -> int:
    ap = argparse.ArgumentParser(description="Exam-solving evaluation report")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--samples", help="directory of *.json sample questions")
    g.add_argument("--synthetic", type=int, help="number of synthetic samples")
    ap.add_argument("--solvers", default="local", help="comma-separated solver names")
    ap.add_argument("--out", help="write JSON here instead of stdout")
    args = ap.parse_args()

    samples = _load_samples(args.samples) if args.samples else _synthetic(args.synthetic)
    solver_names = [s.strip() for s in args.solvers.split(",") if s.strip()]
    report = run_eval(samples, solver_names)
    report["source"] = (
        {"mode": "samples", "path": args.samples}
        if args.samples
        else {"mode": "synthetic", "n": args.synthetic}
    )

    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({len(samples)} samples, solvers={solver_names})")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
