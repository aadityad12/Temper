"""Six-turn SlopCode-style demo benchmark.

SlopLedger is one evolving coding task. Each checkpoint preserves the previous
contract and adds one requirement. Scoring is deterministic: hidden tests measure
correctness, and simple static metrics apply a bounded slop penalty.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


FUNCTION_CONTRACT = """\
Submit a complete Python module containing:

```python
def summarize(transactions, config=None):
    ...
```

Return plain Python dictionaries/lists only. Do not read files, make network
calls, print output, or require third-party packages."""


@dataclass(frozen=True)
class Checkpoint:
    question_id: str
    title: str
    additions: tuple[str, ...]
    loc_budget: int
    branch_budget: int


CHECKPOINTS: tuple[Checkpoint, ...] = (
    Checkpoint(
        "slopledger_1",
        "Basic ledger summary",
        (
            "Include only rows where status is 'posted' and kind is 'purchase'.",
            "Return total_cents as the sum of included amount_cents values.",
            "Return by_category as {category: cents}, sorted by category name.",
        ),
        110,
        30,
    ),
    Checkpoint(
        "slopledger_2",
        "Date windows and merchants",
        (
            "Support inclusive config.start and config.end date filters when present.",
            "Add top_merchants as a list of {'merchant': name, 'total_cents': cents}.",
            "Sort top_merchants by spend descending, then merchant name ascending.",
        ),
        115,
        32,
    ),
    Checkpoint(
        "slopledger_3",
        "Refunds and reversals",
        (
            "Include posted refund rows with negative amount_cents as standalone refunds.",
            "If a refund has reverses='<original id>', exclude both the refund and the original transaction.",
            "Keep totals, categories, and merchants consistent after reversals are removed.",
        ),
        120,
        34,
    ),
    Checkpoint(
        "slopledger_4",
        "Recurring spend detection",
        (
            "Add recurring as a list of repeated merchant/category/amount patterns.",
            "A pattern is recurring when it appears at least three times.",
            "Neighboring dates in the pattern must be 25 to 35 days apart.",
            "Return each pattern as {'merchant', 'category', 'amount_cents', 'count'}.",
        ),
        125,
        36,
    ),
    Checkpoint(
        "slopledger_5",
        "Budgets",
        (
            "Support config.budgets as {category: budget_cents}.",
            "Add over_budget as a list of {'category', 'budget_cents', 'actual_cents', 'over_cents'}.",
            "Include only categories where actual_cents is greater than budget_cents.",
            "Sort over_budget by over_cents descending, then category ascending.",
        ),
        135,
        38,
    ),
    Checkpoint(
        "slopledger_6",
        "Audit robustness",
        (
            "Skip malformed rows safely instead of crashing.",
            "Rows are malformed if required fields are missing, amount_cents is not an int, or date is invalid.",
            "When config.audit is true, add warnings as deterministic {'index', 'reason'} entries for skipped rows.",
            "Use reasons like 'missing required field: amount_cents', 'invalid amount_cents', and 'invalid date'.",
        ),
        145,
        40,
    ),
)


def _prompt_for(checkpoint: Checkpoint) -> str:
    lines = [
        f"SlopLedger checkpoint {checkpoint.question_id[-1]}/6: {checkpoint.title}",
        "",
        "You are extending the same ledger summarizer from earlier checkpoints.",
        "Preserve all previous behavior and add the requirements below.",
        "",
        FUNCTION_CONTRACT,
        "",
        "Cumulative requirements:",
    ]
    for cp in CHECKPOINTS:
        lines.append(f"\n{cp.question_id[-1]}. {cp.title}")
        for item in cp.additions:
            lines.append(f"   - {item}")
        if cp.question_id == checkpoint.question_id:
            break
    lines.extend([
        "",
        "Return only the complete Python module in a python code block.",
    ])
    return "\n".join(lines)


BENCH_QUESTIONS: list[dict] = [
    {
        "question_id": checkpoint.question_id,
        "dimension": f"checkpoint_{checkpoint.question_id[-1]}",
        "prompt": _prompt_for(checkpoint),
    }
    for checkpoint in CHECKPOINTS
]


REFERENCE_CODE = r'''
from datetime import date


def summarize(transactions, config=None):
    """Summarize posted SlopLedger transactions."""
    config = config or {}
    warnings = []
    valid = []
    reversed_ids = set()

    for index, row in enumerate(transactions):
        checked, reason = _validate(row)
        if reason:
            if config.get("audit"):
                warnings.append({"index": index, "reason": reason})
            continue
        if not _in_window(checked["date"], config):
            continue
        valid.append(checked)
        if checked["kind"] == "refund" and checked.get("reverses"):
            reversed_ids.add(checked["id"])
            reversed_ids.add(checked["reverses"])

    included = [
        row for row in valid
        if row["status"] == "posted"
        and row["kind"] in ("purchase", "refund")
        and row["id"] not in reversed_ids
    ]

    by_category = {}
    by_merchant = {}
    for row in included:
        category = row["category"]
        merchant = row["merchant"]
        amount = row["amount_cents"]
        by_category[category] = by_category.get(category, 0) + amount
        by_merchant[merchant] = by_merchant.get(merchant, 0) + amount

    result = {
        "total_cents": sum(row["amount_cents"] for row in included),
        "by_category": dict(sorted(by_category.items())),
        "top_merchants": [
            {"merchant": merchant, "total_cents": total}
            for merchant, total in sorted(by_merchant.items(), key=lambda item: (-item[1], item[0]))
        ],
        "recurring": _recurring(included),
        "over_budget": _over_budget(by_category, config.get("budgets") or {}),
    }
    if config.get("audit"):
        result["warnings"] = warnings
    return result


def _validate(row):
    required = ("id", "date", "merchant", "category", "amount_cents", "status", "kind")
    if not isinstance(row, dict):
        return None, "invalid row"
    for field in required:
        if field not in row:
            return None, f"missing required field: {field}"
    if not isinstance(row["amount_cents"], int) or isinstance(row["amount_cents"], bool):
        return None, "invalid amount_cents"
    try:
        date.fromisoformat(row["date"])
    except Exception:
        return None, "invalid date"
    return dict(row), None


def _in_window(txn_date, config):
    if config.get("start") and txn_date < config["start"]:
        return False
    if config.get("end") and txn_date > config["end"]:
        return False
    return True


def _recurring(rows):
    groups = {}
    for row in rows:
        if row["kind"] != "purchase":
            continue
        key = (row["merchant"], row["category"], row["amount_cents"])
        groups.setdefault(key, []).append(row["date"])

    recurring = []
    for (merchant, category, amount), dates in groups.items():
        ordered = sorted(dates)
        if len(ordered) < 3:
            continue
        gaps_ok = all(25 <= (date.fromisoformat(b) - date.fromisoformat(a)).days <= 35
                      for a, b in zip(ordered, ordered[1:]))
        if gaps_ok:
            recurring.append({
                "merchant": merchant,
                "category": category,
                "amount_cents": amount,
                "count": len(ordered),
            })
    return sorted(recurring, key=lambda item: (item["merchant"], item["category"], item["amount_cents"]))


def _over_budget(by_category, budgets):
    rows = []
    for category, budget in budgets.items():
        actual = by_category.get(category, 0)
        if actual > budget:
            rows.append({
                "category": category,
                "budget_cents": budget,
                "actual_cents": actual,
                "over_cents": actual - budget,
            })
    return sorted(rows, key=lambda item: (-item["over_cents"], item["category"]))
'''


_CASES_BY_CHECKPOINT: dict[str, list[dict[str, Any]]] = {
    "slopledger_1": [
        {
            "name": "posted purchases only",
            "transactions": [
                {"id": "t1", "date": "2026-01-02", "merchant": "Cafe Nia", "category": "food", "amount_cents": 1200, "status": "posted", "kind": "purchase"},
                {"id": "t2", "date": "2026-01-03", "merchant": "Metro", "category": "travel", "amount_cents": 300, "status": "pending", "kind": "purchase"},
                {"id": "t3", "date": "2026-01-04", "merchant": "Cafe Nia", "category": "food", "amount_cents": 900, "status": "posted", "kind": "purchase"},
                {"id": "t4", "date": "2026-01-05", "merchant": "Payroll", "category": "income", "amount_cents": 500000, "status": "posted", "kind": "deposit"},
            ],
            "config": None,
            "expected": {"total_cents": 2100, "by_category": {"food": 2100}},
        },
    ],
    "slopledger_2": [
        {
            "name": "date window and merchant ordering",
            "transactions": [
                {"id": "t1", "date": "2026-02-01", "merchant": "Alpha", "category": "tools", "amount_cents": 4000, "status": "posted", "kind": "purchase"},
                {"id": "t2", "date": "2026-02-10", "merchant": "Beta", "category": "tools", "amount_cents": 2500, "status": "posted", "kind": "purchase"},
                {"id": "t3", "date": "2026-02-15", "merchant": "Beta", "category": "food", "amount_cents": 1700, "status": "posted", "kind": "purchase"},
                {"id": "t4", "date": "2026-03-01", "merchant": "Alpha", "category": "tools", "amount_cents": 9900, "status": "posted", "kind": "purchase"},
            ],
            "config": {"start": "2026-02-05", "end": "2026-02-28"},
            "expected": {
                "total_cents": 4200,
                "by_category": {"food": 1700, "tools": 2500},
                "top_merchants": [{"merchant": "Beta", "total_cents": 4200}],
            },
        },
    ],
    "slopledger_3": [
        {
            "name": "standalone refunds and linked reversals",
            "transactions": [
                {"id": "p1", "date": "2026-03-01", "merchant": "CloudBox", "category": "software", "amount_cents": 7000, "status": "posted", "kind": "purchase"},
                {"id": "r1", "date": "2026-03-02", "merchant": "CloudBox", "category": "software", "amount_cents": -7000, "status": "posted", "kind": "refund", "reverses": "p1"},
                {"id": "p2", "date": "2026-03-03", "merchant": "Books", "category": "education", "amount_cents": 3200, "status": "posted", "kind": "purchase"},
                {"id": "r2", "date": "2026-03-04", "merchant": "Books", "category": "education", "amount_cents": -500, "status": "posted", "kind": "refund"},
            ],
            "config": None,
            "expected": {
                "total_cents": 2700,
                "by_category": {"education": 2700},
                "top_merchants": [{"merchant": "Books", "total_cents": 2700}],
            },
        },
    ],
    "slopledger_4": [
        {
            "name": "recurring monthly spend",
            "transactions": [
                {"id": "s1", "date": "2026-01-01", "merchant": "Streamly", "category": "media", "amount_cents": 1299, "status": "posted", "kind": "purchase"},
                {"id": "s2", "date": "2026-01-31", "merchant": "Streamly", "category": "media", "amount_cents": 1299, "status": "posted", "kind": "purchase"},
                {"id": "s3", "date": "2026-03-02", "merchant": "Streamly", "category": "media", "amount_cents": 1299, "status": "posted", "kind": "purchase"},
                {"id": "g1", "date": "2026-01-02", "merchant": "Grocer", "category": "food", "amount_cents": 1299, "status": "posted", "kind": "purchase"},
            ],
            "config": None,
            "expected": {
                "recurring": [{"merchant": "Streamly", "category": "media", "amount_cents": 1299, "count": 3}],
            },
        },
    ],
    "slopledger_5": [
        {
            "name": "budget overage ordering",
            "transactions": [
                {"id": "f1", "date": "2026-04-01", "merchant": "Market", "category": "food", "amount_cents": 5000, "status": "posted", "kind": "purchase"},
                {"id": "f2", "date": "2026-04-02", "merchant": "Market", "category": "food", "amount_cents": 2500, "status": "posted", "kind": "purchase"},
                {"id": "t1", "date": "2026-04-03", "merchant": "Metro", "category": "travel", "amount_cents": 9000, "status": "posted", "kind": "purchase"},
            ],
            "config": {"budgets": {"food": 6500, "travel": 5000, "media": 2000}},
            "expected": {
                "over_budget": [
                    {"category": "travel", "budget_cents": 5000, "actual_cents": 9000, "over_cents": 4000},
                    {"category": "food", "budget_cents": 6500, "actual_cents": 7500, "over_cents": 1000},
                ],
            },
        },
    ],
    "slopledger_6": [
        {
            "name": "audit malformed rows",
            "transactions": [
                {"id": "ok1", "date": "2026-05-01", "merchant": "Market", "category": "food", "amount_cents": 2200, "status": "posted", "kind": "purchase"},
                {"id": "bad1", "date": "2026-05-02", "merchant": "Market", "category": "food", "status": "posted", "kind": "purchase"},
                {"id": "bad2", "date": "2026-05-03", "merchant": "Taxi", "category": "travel", "amount_cents": "1700", "status": "posted", "kind": "purchase"},
                {"id": "bad3", "date": "not-a-date", "merchant": "Taxi", "category": "travel", "amount_cents": 1700, "status": "posted", "kind": "purchase"},
            ],
            "config": {"audit": True},
            "expected": {
                "total_cents": 2200,
                "by_category": {"food": 2200},
                "warnings": [
                    {"index": 1, "reason": "missing required field: amount_cents"},
                    {"index": 2, "reason": "invalid amount_cents"},
                    {"index": 3, "reason": "invalid date"},
                ],
            },
        },
    ],
}


def _cumulative_cases(question_id: str) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for checkpoint in CHECKPOINTS:
        cases.extend(_CASES_BY_CHECKPOINT[checkpoint.question_id])
        if checkpoint.question_id == question_id:
            return cases
    raise KeyError(f"Unknown SlopLedger checkpoint: {question_id}")


def _checkpoint(question_id: str) -> Checkpoint:
    for checkpoint in CHECKPOINTS:
        if checkpoint.question_id == question_id:
            return checkpoint
    raise KeyError(f"Unknown SlopLedger checkpoint: {question_id}")


def _extract_code(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else text


def run_tests(question_id: str, code: str) -> dict:
    """Run hidden checkpoint tests and return pass/fail details."""
    code = _extract_code(code)
    results = []
    for case in _cumulative_cases(question_id):
        actual = _execute_case(code, case)
        if not actual["ok"]:
            results.append({"name": case["name"], "status": "fail", "detail": actual["error"]})
            continue
        if _contains_expected(actual["result"], case["expected"]):
            results.append({"name": case["name"], "status": "pass"})
        else:
            detail = f"got {actual['result']!r}, expected subset {case['expected']!r}"
            results.append({"name": case["name"], "status": "fail", "detail": detail})

    passed = sum(1 for item in results if item["status"] == "pass")
    total = len(results)
    return {
        "passed": passed,
        "total": total,
        "score": int(round((passed / total) * 100)) if total else 0,
        "results": results,
    }


def judge_bench(question_id: str, harness_code: str) -> dict:
    """Score one SlopLedger checkpoint answer."""
    checkpoint = _checkpoint(question_id)
    tests = run_tests(question_id, harness_code)
    metrics = _slop_metrics(harness_code)
    penalty = _slop_penalty(metrics, checkpoint)
    harness_score = max(0, tests["score"] - penalty)
    verdict = (
        f"{checkpoint.title}: {tests['passed']}/{tests['total']} hidden tests passed; "
        f"slop penalty {penalty} "
        f"(LOC {metrics['loc']}/{checkpoint.loc_budget}, branches {metrics['branches']}/{checkpoint.branch_budget}, "
        f"helpers/classes {metrics['helpers_and_classes']}, duplicate lines {metrics['duplicate_lines']})."
    )
    return {
        "baseline_score": 100,
        "harness_score": harness_score,
        "verdict": verdict,
        "metrics": {
            **metrics,
            "slop_penalty": penalty,
            "tests_passed": tests["passed"],
            "tests_total": tests["total"],
        },
    }


def aggregate_results(questions: list[Any]) -> dict:
    """Aggregate per-checkpoint judge results into the final dashboard report."""
    judged = [q for q in questions if getattr(q, "judge_result", None)]
    if not judged:
        score = 0
        verdict = "No SlopLedger checkpoints were judged."
        tests_passed = 0
        tests_total = 0
        penalty = 0
    else:
        score = round(sum(q.judge_result["harness_score"] for q in judged) / len(judged))
        tests_passed = sum(q.judge_result.get("metrics", {}).get("tests_passed", 0) for q in judged)
        tests_total = sum(q.judge_result.get("metrics", {}).get("tests_total", 0) for q in judged)
        penalty = sum(q.judge_result.get("metrics", {}).get("slop_penalty", 0) for q in judged)
        verdict = (
            f"{len(judged)}/6 checkpoints judged; {tests_passed}/{tests_total} hidden tests passed; "
            f"total slop penalty {penalty}."
        )

    return {
        "dimensions": {
            "slopcode_trajectory": {
                "baseline_score": 100,
                "harness_score": score,
                "delta": score - 100,
                "status": "PASSING" if score >= 90 else "NEEDS_PATCH",
                "verdict": verdict,
                "test_cases_run": tests_total,
                "metrics": {
                    "checkpoints_judged": len(judged),
                    "tests_passed": tests_passed,
                    "tests_total": tests_total,
                    "slop_penalty": penalty,
                },
            }
        }
    }


def _execute_case(code: str, case: dict[str, Any]) -> dict:
    script = (
        f"{code}\n\n"
        "import json\n"
        f"transactions = {case['transactions']!r}\n"
        f"config = {case['config']!r}\n"
        "try:\n"
        "    result = summarize(transactions, config)\n"
        "    print(json.dumps({'ok': True, 'result': result}, sort_keys=True))\n"
        "except Exception as exc:\n"
        "    print(json.dumps({'ok': False, 'error': type(exc).__name__ + ': ' + str(exc)}))\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=4,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}

    if proc.returncode != 0:
        error = (proc.stderr or proc.stdout or "process failed").strip().splitlines()[-1]
        return {"ok": False, "error": error}

    try:
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        return json.loads(lines[-1])
    except Exception as exc:
        return {"ok": False, "error": f"invalid result JSON: {exc}"}


def _contains_expected(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and _contains_expected(actual[key], value)
                   for key, value in expected.items())
    return actual == expected


def _slop_metrics(code: str) -> dict[str, int]:
    code = _extract_code(code)
    lines = [
        line.strip()
        for line in code.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    normalized = [re.sub(r"\s+", " ", line) for line in lines]
    duplicate_lines = len(normalized) - len(set(normalized))

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {"loc": len(lines), "helpers_and_classes": 0, "branches": 0, "duplicate_lines": duplicate_lines}

    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    helpers_and_classes = max(0, len(functions) - 1) + len(classes)
    branch_nodes = (ast.If, ast.For, ast.While, ast.Try, ast.ExceptHandler, ast.BoolOp, ast.IfExp, ast.Match)
    branches = sum(1 for node in ast.walk(tree) if isinstance(node, branch_nodes))

    return {
        "loc": len(lines),
        "helpers_and_classes": helpers_and_classes,
        "branches": branches,
        "duplicate_lines": duplicate_lines,
    }


def _slop_penalty(metrics: dict[str, int], checkpoint: Checkpoint) -> int:
    loc_penalty = min(12, max(0, metrics["loc"] - checkpoint.loc_budget))
    branch_penalty = min(8, max(0, metrics["branches"] - checkpoint.branch_budget))
    helper_penalty = min(6, max(0, metrics["helpers_and_classes"] - 8) * 2)
    duplicate_penalty = min(4, max(0, metrics["duplicate_lines"] - 8))
    return min(30, loc_penalty + branch_penalty + helper_penalty + duplicate_penalty)
