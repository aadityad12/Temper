#!/usr/bin/env python3
"""Demo player — renders the full @eval → @patch narrative from pre-cached reports.

Runs without a live server or a DeepSeek API key. Used for hackathon demos
and CI smoke tests.

Usage:
    python demo.py           # render both eval and diff reports back-to-back
    python demo.py eval      # render only the pre-patch eval report
    python demo.py patch     # render only the post-patch diff report
"""

import json
import sys
import time
from pathlib import Path

import renderer

DEMO_DIR = Path(__file__).parent / "demo_cache"


def _load(filename: str) -> dict:
    path = DEMO_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Demo cache missing: {path}. Run the eval pipeline once to generate it.")
    return json.loads(path.read_text())


def demo_eval() -> None:
    saved = _load("eval_report.json")
    report = saved["report"]
    session_id = saved["session_id"]
    patches = _load("patches.json")
    renderer.render_full(report, session_id, len(patches))


def demo_patch() -> None:
    pre = _load("eval_report.json")
    post = _load("reeval_report.json")
    renderer.render_diff(pre["report"], post["report"], post["session_id"])


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    if cmd in ("eval", "all"):
        demo_eval()
    if cmd in ("patch", "all"):
        if cmd == "all":
            time.sleep(0.5)
        demo_patch()


if __name__ == "__main__":
    main()
