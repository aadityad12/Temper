#!/usr/bin/env python3
"""@eval — collect bundle, run test loop against DeepSeek, render report.

Usage:
    python eval.py [env_dir]          # env_dir defaults to fixtures/villain_env

Set TEMPER_OFFLINE=true in .env (or env) to use the mock server without
a live DeepSeek key or Antigravity instance.
"""

import json
import pathlib
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

import bundle as bundle_mod
import client
import harness
import renderer

LOCAL_DIR = Path(__file__).parent
PATCHES_DIR = LOCAL_DIR / "patches"


def run_test_loop(session_id: str, api_bundle: dict, label: str = "") -> None:
    """Poll /next-question → harness → /submit-answer until done."""
    q_num = 0
    prefix = f"[{label}] " if label else ""
    while True:
        resp = client.next_question(session_id)
        if resp["status"] == "done":
            print(f"{prefix}All questions answered.")
            break

        q_num += 1
        qid = resp["question_id"]
        dim = resp["dimension"]
        prompt = resp["prompt"]

        print(f"{prefix}Q{q_num} [{dim}] {qid} …", end=" ", flush=True)
        result = harness.run(api_bundle, prompt)
        client.submit_answer(session_id, qid, result["answer"], result["latency_ms"])
        print(f"{result['latency_ms']}ms")


def save_patches(patches: list, env_dir: pathlib.Path) -> None:
    """Write patch files to local/patches/."""
    PATCHES_DIR.mkdir(exist_ok=True)
    for p in patches:
        dest = PATCHES_DIR / p["filename"].replace("/", "_")
        dest.write_text(p["content"])
    print(f"Wrote {len(patches)} patch file(s) to {PATCHES_DIR}/")


def main(env_dir: str = None) -> None:
    if env_dir is None:
        env_dir = str(Path(__file__).parent.parent / "fixtures" / "villain_env")

    env_path = pathlib.Path(env_dir)
    print(f"\n[temper] @eval  env={env_path}")

    # 1. Collect bundle
    print("Collecting bundle …")
    full_bundle = bundle_mod.collect(env_path)
    api_bundle = bundle_mod.api_shape(full_bundle)
    print(f"  skills: {[s['name'] for s in api_bundle['skills']]}")
    print(f"  tools:  {[t['name'] for t in api_bundle['tools']]}")

    # 2. Register
    print("Registering with server …")
    session_id = client.register(api_bundle)
    print(f"Session: {session_id}")

    # Save session id immediately
    (LOCAL_DIR / "last_session_id.txt").write_text(session_id)

    # 3. Test loop
    print("Running test loop …")
    run_test_loop(session_id, api_bundle)

    # 4. Poll for results
    print("Polling for results …")
    results = client.get_results(session_id)

    report = results["report"]
    patches = results.get("patches", [])

    # 5. Save artifacts
    (LOCAL_DIR / "last_report.json").write_text(
        json.dumps({"session_id": session_id, "report": report}, indent=2)
    )
    (LOCAL_DIR / "last_patches.json").write_text(json.dumps(patches, indent=2))

    if patches:
        save_patches(patches, env_path)

    # 6. Render
    renderer.render_full(report, session_id, len(patches))


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(arg)
