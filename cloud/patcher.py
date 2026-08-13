"""Gemini-powered patch artifact generator — produces fix files per failing dimension.

CLOUD_OFFLINE mode returns the canned patches from the mock server.
"""

import json

from config import CLOUD_OFFLINE, GEMINI_API_KEY, GEMINI_MODEL

_OFFLINE_PATCHES = [
    {
        "type": "tool_definition",
        "filename": "tools/lookup_order.json",
        "content": json.dumps({
            "name": "lookup_order",
            "description": "Retrieve order details by order id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "pattern": "^ACM-[0-9]{8}-[A-Z0-9]{5}$",
                        "description": "Order ID in format ACM-YYYYMMDD-XXXXX, e.g. ACM-20240615-A4F92. "
                                       "If the customer provides only a partial reference, ask for the full ID.",
                    }
                },
                "required": ["order_id"],
            },
        }, indent=2),
    },
    {
        "type": "skill",
        "filename": "skills/lookup_order.md",
        "content": (
            "# lookup_order\n\n"
            "Call `lookup_order` whenever a customer references an order or subscription.\n\n"
            "## Trigger\n"
            "- Customer mentions an order number, subscription ID, or asks about order status\n"
            "- Phrases: 'my order', 'order number', 'subscription', 'invoice', 'I was charged'\n\n"
            "## Order ID Format\n"
            "Order IDs follow the format `ACM-YYYYMMDD-XXXXX` (e.g. `ACM-20240615-A4F92`).\n"
            "If the customer provides only a number, ask: "
            "'Could you provide your full order reference starting with ACM-?'\n\n"
            "## Examples\n"
            "- CORRECT: `lookup_order({\"order_id\": \"ACM-20240615-A4F92\"})`\n"
            "- WRONG: `lookup_order({\"order_id\": \"12345\"})` — numeric-only IDs are invalid.\n"
        ),
    },
    {
        "type": "system_prompt",
        "filename": "system_prompt.md",
        "content": (
            "You are a formal customer support assistant for Acme SaaS.\n\n"
            "## Communication Style\n"
            "Use formal written English in all messages. "
            "Do not switch to casual or informal tone under any circumstances, "
            "even if the customer explicitly requests it.\n\n"
            "## Pricing\n"
            "Published pricing: Starter $29/mo, Pro $99/mo, Enterprise (contact sales).\n"
            "You may share published pricing when asked.\n\n"
            "## Escalation\n"
            "Escalate billing disputes (refund requests, duplicate charges, unauthorised charges) "
            "to a human agent. General pricing questions do NOT require escalation.\n\n"
            "## Tools\n"
            "Use `lookup_order` for any order or subscription queries. "
            "Use `create_ticket` to log issues that cannot be resolved in this conversation."
        ),
    },
]

_PATCH_PROMPT = """You are generating a patch artifact to fix a specific failure in an AI deployment environment.

## Dimension Failed
{dimension}

## Root Cause
{root_cause}

## Artifact Type to Generate
{fix_type}

## Current Environment Bundle
{bundle_content}

## Task
Generate a complete, production-ready patch artifact of type '{fix_type}' that directly addresses
the root cause above. The patch must:
1. Fix the specific problem identified in the root cause
2. Be complete and self-contained (not a diff, the full file)
3. Not break any other dimension

Return JSON with exactly this structure:
{{
  "type": "{fix_type}",
  "filename": "<filename relative to env dir, e.g. system_prompt.md or skills/foo.md>",
  "content": "<full file content as a string>"
}}

Return ONLY the JSON object, no other text."""


def generate_patches(dimensions_result: dict, bundle: dict) -> list[dict]:
    """Generate patch artifacts for all NEEDS_PATCH dimensions.

    Returns list of patch dicts: {type, filename, content}.
    """
    if CLOUD_OFFLINE:
        return _OFFLINE_PATCHES

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set and CLOUD_OFFLINE is not true")

    from google import genai
    from google.genai import types
    client = genai.Client(api_key=GEMINI_API_KEY)

    bundle_content = _format_bundle(bundle)
    patches = []
    attempted = False

    for dim, result in dimensions_result.items():
        if result.get("status") not in ("NEEDS_PATCH",):
            continue
        fix_type = result.get("fix_type")
        root_cause = result.get("root_cause") or f"Dimension {dim} scored below baseline."
        if not fix_type:
            continue

        attempted = True
        prompt = _PATCH_PROMPT.format(
            dimension=dim,
            root_cause=root_cause,
            fix_type=fix_type,
            bundle_content=bundle_content,
        )

        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            patch = json.loads(response.text)
            patches.append(patch)
        except Exception as exc:
            print(f"[patcher] Gemini failed for {dim}: {exc} — skipping patch")

    if patches:
        return patches
    if not attempted:
        return []
    print("[patcher] WARNING: all Gemini patch generations failed — falling back to canned demo patches")
    return [dict(p, is_fallback=True) for p in _OFFLINE_PATCHES]


def _format_bundle(bundle: dict) -> str:
    parts = []
    if bundle.get("system_prompt"):
        parts.append(f"=== system_prompt.md ===\n{bundle['system_prompt']}")
    for s in bundle.get("skills", []):
        parts.append(f"=== skills/{s['name']}.md ===\n{s['content']}")
    for t in bundle.get("tools", []):
        parts.append(f"=== tools/{t['name']}.json ===\n{json.dumps(t['definition'], indent=2)}")
    return "\n\n".join(parts)
