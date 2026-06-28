"""Pre-defined coding benchmark question + test executor.

A single two_sum question drawn from SlopCode-style bench.
Scoring is test-based (subprocess execution), not LLM-judged.
"""

import re
import subprocess
import sys
from typing import Any

from config import CLOUD_OFFLINE

# ── question bank ─────────────────────────────────────────────────────────────

TWO_SUM_PROMPT = """\
Implement the following Python function:

```python
def two_sum(nums: list[int], target: int) -> list[int]:
    \"\"\"Return the indices of the two numbers that add up to target.\"\"\"
```

Exactly one solution always exists. You may not use the same element twice.
Return indices in any order.

Your answer must be a complete Python function definition for `two_sum`."""

BENCH_QUESTIONS: list[dict] = [
    {
        "question_id": "bench_two_sum",
        "dimension": "coding_bench",
        "prompt": TWO_SUM_PROMPT,
    }
]

# Expected outputs sorted so order doesn't matter
_TEST_CASES: list[dict[str, Any]] = [
    {"args": ([2, 7, 11, 15], 9),       "expected": [0, 1]},
    {"args": ([3, 2, 4], 6),            "expected": [1, 2]},
    {"args": ([3, 3], 6),               "expected": [0, 1]},
    {"args": ([1, 2, 3, 4, 5], 9),      "expected": [3, 4]},
    {"args": ([-1, -2, -3, -4, -5], -8),"expected": [2, 4]},
]

# Correct offline answer used as baseline when CLOUD_OFFLINE=true
_OFFLINE_BASELINE_CODE = """\
def two_sum(nums, target):
    seen = {}
    for i, n in enumerate(nums):
        if target - n in seen:
            return [seen[target - n], i]
        seen[n] = i
"""


# ── code extraction ───────────────────────────────────────────────────────────

def _extract_code(text: str) -> str:
    """Strip markdown fences if present; return the raw code string."""
    text = text.strip()
    # Remove ```python ... ``` or ``` ... ``` blocks
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


# ── test executor ─────────────────────────────────────────────────────────────

def run_tests(code: str) -> dict:
    """Execute code against all test cases. Returns {passed, total, score, results}."""
    code = _extract_code(code)
    passed = 0
    results = []

    for tc in _TEST_CASES:
        args, expected = tc["args"], tc["expected"]
        script = (
            f"{code}\n\n"
            f"result = two_sum({list(args[0])!r}, {args[1]!r})\n"
            f"assert sorted(result) == sorted({expected!r}), "
            f"f'got {{result}}, expected {expected!r}'\n"
            f"print('PASS')\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0 and "PASS" in proc.stdout:
                passed += 1
                results.append({"status": "pass"})
            else:
                err = (proc.stderr or proc.stdout).strip().splitlines()[-1] if (proc.stderr or proc.stdout) else "wrong answer"
                results.append({"status": "fail", "detail": err})
        except subprocess.TimeoutExpired:
            results.append({"status": "timeout"})
        except Exception as exc:
            results.append({"status": "error", "detail": str(exc)})

    total = len(_TEST_CASES)
    return {
        "passed": passed,
        "total": total,
        "score": int(passed / total * 100),
        "results": results,
    }


# ── bench judge ───────────────────────────────────────────────────────────────

def judge_bench(harness_code: str, baseline_code: str) -> dict:
    """Run tests on both answers. Returns {baseline_score, harness_score, verdict}.

    Return shape is identical to judge_single_question so the existing
    pipeline (SSE events, dashboard) works without changes.
    """
    if CLOUD_OFFLINE:
        # Use the correct solution as the baseline in offline mode
        baseline_code = _OFFLINE_BASELINE_CODE

    h = run_tests(harness_code)
    b = run_tests(baseline_code)

    verdict = (
        f"AGY: {h['passed']}/{h['total']} tests passed  |  "
        f"Bare model: {b['passed']}/{b['total']} tests passed"
    )
    return {
        "baseline_score": b["score"],
        "harness_score": h["score"],
        "verdict": verdict,
    }
