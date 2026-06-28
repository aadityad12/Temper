"""Bundle collector — reads an env directory and assembles + validates the bundle."""

import hashlib
import json
import pathlib
import uuid
from datetime import datetime, timezone

import jsonschema

ROOT = pathlib.Path(__file__).parent.parent
_BUNDLE_SCHEMA = json.loads((ROOT / "schemas" / "environment_bundle.schema.json").read_text())


def collect(env_dir: str | pathlib.Path) -> dict:
    """Read system_prompt.md, skills/*.md, tools/*.json from env_dir.

    Returns a full bundle dict (with bundle_id, timestamp, bundle_hash) that
    validates against schemas/environment_bundle.schema.json.
    """
    d = pathlib.Path(env_dir)
    if not d.is_dir():
        raise ValueError(f"env_dir does not exist: {d}")

    sp_path = d / "system_prompt.md"
    system_prompt = sp_path.read_text() if sp_path.exists() else None

    skills = []
    skills_dir = d / "skills"
    if skills_dir.is_dir():
        for f in sorted(skills_dir.glob("*.md")):
            skills.append({"name": f.stem, "content": f.read_text()})

    tools = []
    tools_dir = d / "tools"
    if tools_dir.is_dir():
        for f in sorted(tools_dir.glob("*.json")):
            tools.append({"name": f.stem, "definition": json.loads(f.read_text())})

    content_hash = _hash(system_prompt, skills, tools)

    bundle = {
        "bundle_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bundle_hash": content_hash,
        "system_prompt": system_prompt,
        "skills": skills,
        "tools": tools,
    }

    jsonschema.validate(bundle, _BUNDLE_SCHEMA)
    return bundle


def api_shape(bundle: dict) -> dict:
    """Strip metadata fields — returns only what POST /register expects."""
    return {
        "system_prompt": bundle["system_prompt"],
        "skills": bundle["skills"],
        "tools": bundle["tools"],
    }


def _hash(system_prompt, skills, tools) -> str:
    h = hashlib.sha256()
    h.update((system_prompt or "").encode())
    for s in skills:
        h.update(s["name"].encode())
        h.update(s["content"].encode())
    for t in tools:
        h.update(t["name"].encode())
        h.update(json.dumps(t["definition"], sort_keys=True).encode())
    return h.hexdigest()
