"""Local harness runner — calls DeepSeek with the full bundle as context.

In offline mode (TEMPER_OFFLINE=true), returns a deterministic canned
answer so the test loop works without a live DeepSeek API key.
"""

import json
import os
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

OFFLINE = os.getenv("TEMPER_OFFLINE", "").lower() == "true"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

_OFFLINE_ANSWER = (
    "Thank you for reaching out to Acme SaaS support. "
    "I would be happy to assist you with your enquiry. "
    "Could you please provide more details so I can look into this for you?"
)
_OFFLINE_LATENCY_MS = 312


def run(bundle: dict, question_prompt: str) -> dict:
    """Run the harness for one question.

    Args:
        bundle: the api-shaped bundle (system_prompt, skills, tools).
        question_prompt: the question text from /next-question.

    Returns:
        {"answer": str, "latency_ms": int}
        answer includes serialised tool calls if the model made any.
    """
    if OFFLINE:
        return {"answer": _OFFLINE_ANSWER, "latency_ms": _OFFLINE_LATENCY_MS}

    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set and TEMPER_OFFLINE is not true")

    system_ctx = _build_system_context(bundle)

    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package not installed — run: pip install openai")

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

    t0 = time.monotonic()
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": system_ctx},
            {"role": "user", "content": question_prompt},
        ],
        tools=_tool_defs(bundle),
        tool_choice="auto",
        temperature=0,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    answer = _extract_answer(response)
    return {"answer": answer, "latency_ms": latency_ms}


def _build_system_context(bundle: dict) -> str:
    parts = []

    if bundle.get("system_prompt"):
        parts.append(bundle["system_prompt"])

    if bundle.get("skills"):
        parts.append("\n\n---\n# Skills\n")
        for skill in bundle["skills"]:
            parts.append(f"\n## {skill['name']}\n{skill['content']}")

    if bundle.get("tools"):
        parts.append("\n\n---\n# Tool Definitions\n")
        for tool in bundle["tools"]:
            parts.append(f"\n## {tool['name']}\n```json\n{json.dumps(tool['definition'], indent=2)}\n```")

    return "".join(parts)


def _tool_defs(bundle: dict) -> list | None:
    tools = bundle.get("tools", [])
    if not tools:
        return None
    result = []
    for t in tools:
        defn = t["definition"]
        result.append({
            "type": "function",
            "function": {
                "name": defn.get("name", t["name"]),
                "description": defn.get("description", ""),
                "parameters": defn.get("parameters", {}),
            },
        })
    return result or None


def _extract_answer(response) -> str:
    """Serialize the full response including any tool calls as a string."""
    msg = response.choices[0].message

    if msg.tool_calls:
        parts = []
        if msg.content:
            parts.append(msg.content)
        for tc in msg.tool_calls:
            parts.append(json.dumps({
                "tool_call": tc.function.name,
                "arguments": json.loads(tc.function.arguments),
            }))
        return "\n".join(parts)

    return msg.content or ""
