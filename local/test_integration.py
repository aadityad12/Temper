#!/usr/bin/env python3
"""Integration test — runs the full @eval → @patch pipeline against the cloud
server in CLOUD_OFFLINE mode and asserts that the villain env numbers land in
the expected bands.

Usage:
    python test_integration.py              # uses cloud offline mode (default)
    CLOUD_OFFLINE=false python test_integration.py  # uses live APIs (slower)

Pass --help for options.
"""

import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).parent.parent
LOCAL = ROOT / "local"
CLOUD = ROOT / "cloud"

CLOUD_PORT = 8002   # separate port so it doesn't clash with make run-cloud-offline (8001)
BASE_URL = f"http://localhost:{CLOUD_PORT}"

# ── expected bands (direction + threshold, not exact points) ─────────────────
# direction: "negative" | "positive" | "near_zero"
# threshold: minimum absolute delta that must be achieved

EXPECTED_OFFLINE = {
    "instruction_adherence": {"direction": "negative", "threshold": 20, "status": "NEEDS_PATCH"},
    "tool_accuracy":         {"direction": "negative", "threshold": 30, "status": "NEEDS_PATCH"},
    "output_format":         {"direction": "near_zero", "threshold": 0,  "status": "PASSING"},
    "skill_trigger":         {"direction": "negative", "threshold": 5,  "status": "NEEDS_PATCH"},
    "latency_delta":         {"direction": "negative", "threshold": 10, "status": "NEEDS_PATCH"},
    "error_recovery":        {"direction": "near_zero", "threshold": 0,  "status": "STRUCTURAL_LIMITATION"},
}

EXPECTED_REEVAL_OFFLINE = {
    "instruction_adherence": {"min_move": 30, "status": "RESOLVED"},
    "tool_accuracy":         {"min_move": 30, "status": "RESOLVED"},
}

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def _assert(condition: bool, msg: str) -> bool:
    if condition:
        print(f"  {PASS}  {msg}")
    else:
        print(f"  {FAIL}  {msg}")
    return condition


def check_eval_report(report: dict, orig_report: dict | None = None) -> list[str]:
    failures = []
    dims = report["dimensions"]

    for dim, spec in EXPECTED_OFFLINE.items():
        if dim not in dims:
            failures.append(f"{dim}: missing from report")
            continue
        d = dims[dim]
        delta = d["delta"]
        status = d.get("status", "")
        direction = spec["direction"]
        threshold = spec["threshold"]

        if direction == "negative":
            ok = _assert(delta <= -threshold,
                         f"{dim}: delta={delta} (want ≤ -{threshold})")
        elif direction == "positive":
            ok = _assert(delta >= threshold,
                         f"{dim}: delta={delta} (want ≥ +{threshold})")
        else:  # near_zero
            ok = _assert(abs(delta) <= 10,
                         f"{dim}: delta={delta} (want within ±10)")

        if not ok:
            failures.append(f"{dim}: delta direction/threshold failed")

        ok2 = _assert(status == spec["status"],
                      f"{dim}: status={status!r} (want {spec['status']!r})")
        if not ok2:
            failures.append(f"{dim}: status mismatch")

    return failures


def check_reeval_report(orig_report: dict, reeval_report: dict) -> list[str]:
    failures = []
    orig_dims = orig_report["dimensions"]
    new_dims = reeval_report["dimensions"]

    for dim, spec in EXPECTED_REEVAL_OFFLINE.items():
        if dim not in new_dims:
            _assert(False, f"{dim}: missing from reeval report")
            failures.append(f"{dim}: missing from reeval")
            continue
        before = orig_dims[dim]["harness_score"]
        after = new_dims[dim]["harness_score"]
        move = after - before
        status = new_dims[dim].get("status", "")

        ok = _assert(move >= spec["min_move"],
                     f"{dim}: {before}→{after} move=+{move} (want ≥+{spec['min_move']})")
        if not ok:
            failures.append(f"{dim}: move too small")

        ok2 = _assert(status == spec["status"],
                      f"{dim}: reeval status={status!r} (want {spec['status']!r})")
        if not ok2:
            failures.append(f"{dim}: reeval status mismatch")

    # Error recovery should stay STRUCTURAL_LIMITATION
    if "error_recovery" in orig_dims:
        er_status = orig_dims["error_recovery"].get("status", "")
        _assert(er_status == "STRUCTURAL_LIMITATION",
                f"error_recovery: stays STRUCTURAL_LIMITATION (got {er_status!r})")

    return failures


def run_offline_pipeline() -> tuple[dict, dict]:
    """Start cloud server in offline mode, run eval + patch, return reports."""
    env_dir = str(ROOT / "fixtures" / "villain_env")

    # restore villain_env to clean state
    subprocess.run(["git", "checkout", "fixtures/villain_env/"], cwd=ROOT, check=True,
                   capture_output=True)
    for f in ["fixtures/villain_env/skills/get_order_usage.md",
              "fixtures/villain_env/tools/get_order.json"]:
        (ROOT / f).unlink(missing_ok=True)

    # start cloud server
    server_env = {**os.environ, "CLOUD_OFFLINE": "true",
                  "CLOUD_PORT": str(CLOUD_PORT)}
    server = subprocess.Popen(
        [str(CLOUD / ".venv" / "bin" / "python"), str(CLOUD / "main.py")],
        env=server_env, cwd=CLOUD,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    try:
        time.sleep(2)  # wait for startup

        client_env = {**os.environ, "TEMPER_OFFLINE": "false",
                      "ANTIGRAVITY_BASE_URL": BASE_URL}

        # run @eval
        subprocess.run(
            [str(LOCAL / ".venv" / "bin" / "python"), str(LOCAL / "eval.py"), env_dir],
            env=client_env, cwd=LOCAL, check=True,
        )

        # run @patch
        subprocess.run(
            [str(LOCAL / ".venv" / "bin" / "python"), str(LOCAL / "patch.py"), env_dir],
            env=client_env, cwd=LOCAL, check=True,
        )

        report = json.loads((LOCAL / "last_report.json").read_text())["report"]
        reeval = json.loads((LOCAL / "last_reeval_report.json").read_text())["report"]
        return report, reeval

    finally:
        server.terminate()
        server.wait()
        # restore villain_env
        subprocess.run(["git", "checkout", "fixtures/villain_env/"], cwd=ROOT,
                       capture_output=True)
        for f in ["fixtures/villain_env/skills/get_order_usage.md",
                  "fixtures/villain_env/tools/get_order.json",
                  "fixtures/villain_env/skills/lookup_order.md"]:
            (ROOT / f).unlink(missing_ok=True)


def main() -> int:
    print("=" * 60)
    print("TEMPER Integration Test — villain environment")
    print("=" * 60)

    use_live = os.getenv("CLOUD_OFFLINE", "true").lower() != "true"

    if use_live:
        print("[mode] LIVE — reading from last_report.json / last_reeval_report.json")
        print("       (run make test-cloud first to populate these files)")
        try:
            report = json.loads((LOCAL / "last_report.json").read_text())["report"]
            reeval = json.loads((LOCAL / "last_reeval_report.json").read_text())["report"]
        except FileNotFoundError as e:
            print(f"ERROR: {e}")
            print("Run 'make test-cloud' first to generate the report files.")
            return 1
    else:
        print("[mode] OFFLINE — running full pipeline with scripted responses")
        report, reeval = run_offline_pipeline()

    print()
    print("── Eval report assertions ──────────────────────────────")
    eval_failures = check_eval_report(report)

    print()
    print("── Re-eval report assertions ───────────────────────────")
    reeval_failures = check_reeval_report(report, reeval)

    print()
    all_failures = eval_failures + reeval_failures
    if not all_failures:
        print(f"{'=' * 60}")
        print(f"  ALL ASSERTIONS PASSED")
        print(f"{'=' * 60}")
        return 0
    else:
        print(f"{'=' * 60}")
        print(f"  {len(all_failures)} ASSERTION(S) FAILED:")
        for f in all_failures:
            print(f"    - {f}")
        print(f"{'=' * 60}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
