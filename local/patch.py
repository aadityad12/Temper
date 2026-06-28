#!/usr/bin/env python3
"""@patch — apply server-generated patches, trigger re-eval, render diff report.

Usage:
    python patch.py [env_dir]          # env_dir defaults to fixtures/villain_env

Requires a prior @eval run (reads local/last_session_id.txt + local/last_report.json
+ local/patches/).
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
from eval import run_test_loop

LOCAL_DIR = Path(__file__).parent
PATCHES_DIR = LOCAL_DIR / "patches"

_PATCH_TYPE_MAP = {
    "system_prompt": "system_prompt.md",
    "skill": None,          # filename comes from the patch itself
    "tool_definition": None,
}


def _patch_dest(patch: dict, env_dir: pathlib.Path) -> pathlib.Path:
    """Resolve where a patch file should land in the env directory."""
    filename = patch["filename"]
    # Strip leading path segments that match top-level env dir structure
    # e.g. "skills/foo.md" → env_dir/skills/foo.md
    #      "system_prompt.md" → env_dir/system_prompt.md
    #      "tools/bar.json" → env_dir/tools/bar.json
    return env_dir / filename


def _load_prior_state() -> tuple[str, dict]:
    """Read last_session_id.txt and last_report.json. Raises if missing."""
    sid_path = LOCAL_DIR / "last_session_id.txt"
    report_path = LOCAL_DIR / "last_report.json"

    if not sid_path.exists():
        raise FileNotFoundError(
            "No prior eval found. Run @eval first (local/last_session_id.txt missing)."
        )
    if not report_path.exists():
        raise FileNotFoundError(
            "No prior report found. Run @eval first (local/last_report.json missing)."
        )

    session_id = sid_path.read_text().strip()
    saved = json.loads(report_path.read_text())
    return session_id, saved["report"]


def _load_patches() -> list[dict]:
    """Load all patch files from local/patches/. Raises if none found."""
    if not PATCHES_DIR.exists():
        raise FileNotFoundError("local/patches/ not found. Run @eval first.")

    patches = []
    for f in sorted(PATCHES_DIR.iterdir()):
        content = f.read_text()
        name = f.name
        # Reconstruct the patch dict from the saved file
        # Filename format saved by eval.py: "type_filename" flattened with _
        # We stored the raw patch list in last_report.json — check there first.
    return None  # signal to read from report json


def _load_patches_from_report() -> list[dict]:
    """Patches are saved in last_report.json (full results payload)."""
    path = LOCAL_DIR / "last_patches.json"
    if path.exists():
        return json.loads(path.read_text())
    return []


def _apply_patches(patches: list[dict], env_dir: pathlib.Path) -> int:
    """Write each patch to the env directory. Returns count applied."""
    applied = 0
    for p in patches:
        dest = _patch_dest(p, env_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(p["content"])
        print(f"  patched: {dest.relative_to(env_dir.parent.parent)}")
        applied += 1
    return applied


def main(env_dir: str = None) -> None:
    if env_dir is None:
        env_dir = str(Path(__file__).parent.parent / "fixtures" / "villain_env")

    env_path = pathlib.Path(env_dir)
    print(f"\n[temper] @patch  env={env_path}")

    # 1. Load prior state
    session_id, orig_report = _load_prior_state()
    print(f"Prior session: {session_id}")

    patches = _load_patches_from_report()
    if not patches:
        print("No patches available. Run @eval first or check local/last_patches.json.")
        sys.exit(1)

    # 2. Determine dimensions to re-eval
    dims = orig_report["dimensions"]
    from renderer import _infer_status
    patched_dims = [
        dim for dim, d in dims.items()
        if _infer_status(d) == "NEEDS_PATCH"
    ]
    structural_dims = [
        dim for dim, d in dims.items()
        if _infer_status(d) == "STRUCTURAL_LIMITATION"
    ]

    print(f"Patched dimensions: {patched_dims}")
    if structural_dims:
        print(f"  (skipping structural limitations: {structural_dims})")

    if not patched_dims:
        print("No patchable dimensions with negative delta. Nothing to re-eval.")
        sys.exit(0)

    # 3. Apply patches
    print(f"Applying {len(patches)} patch(es) to {env_path} …")
    applied = _apply_patches(patches, env_path)
    print(f"Applied {applied} file(s).")

    # 4. Collect updated bundle
    print("Collecting updated bundle …")
    full_bundle = bundle_mod.collect(env_path)
    api_bundle = bundle_mod.api_shape(full_bundle)

    # 5. Trigger re-eval
    print("Triggering re-evaluation …")
    reeval_session_id = client.reeval(session_id, patched_dims, api_bundle)
    print(f"Re-eval session: {reeval_session_id}")

    # 6. Test loop (only patched-dimension questions)
    print("Running re-eval test loop …")
    run_test_loop(reeval_session_id, api_bundle, label="reeval")

    # 7. Poll for results
    print("Polling for re-eval results …")
    results = client.get_results(reeval_session_id)
    reeval_report = results["report"]

    # 8. Save
    (LOCAL_DIR / "last_reeval_report.json").write_text(
        json.dumps({"session_id": reeval_session_id, "report": reeval_report}, indent=2)
    )

    # 9. Render diff
    renderer.render_diff(orig_report, reeval_report, reeval_session_id)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(arg)
