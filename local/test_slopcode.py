#!/usr/bin/env python3
"""Smoke tests for the SlopLedger demo bench."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "cloud"))

from bench import BENCH_QUESTIONS, REFERENCE_CODE, judge_bench, run_tests  # noqa: E402


INCOMPLETE_CODE = """\
def summarize(transactions, config=None):
    total = 0
    by_category = {}
    for row in transactions:
        if row.get("status") == "posted" and row.get("kind") == "purchase":
            total += row.get("amount_cents", 0)
            category = row.get("category")
            by_category[category] = by_category.get(category, 0) + row.get("amount_cents", 0)
    return {"total_cents": total, "by_category": by_category}
"""


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_reference_scores_100() -> None:
    for question in BENCH_QUESTIONS:
        result = judge_bench(question["question_id"], REFERENCE_CODE)
        _assert(
            result["harness_score"] == 100,
            f"{question['question_id']} reference score was {result['harness_score']}",
        )


def test_incomplete_solution_falls_below_reference() -> None:
    result = judge_bench("slopledger_6", INCOMPLETE_CODE)
    _assert(result["baseline_score"] == 100, "baseline must stay fixed at 100")
    _assert(result["harness_score"] < 100, "incomplete solution should score below reference")


def test_checkpoint_6_audit_does_not_crash() -> None:
    result = run_tests("slopledger_6", REFERENCE_CODE)
    _assert(result["passed"] == result["total"], f"audit checkpoint failed: {result}")


def main() -> int:
    tests = [
        test_reference_scores_100,
        test_incomplete_solution_falls_below_reference,
        test_checkpoint_6_audit_does_not_crash,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
