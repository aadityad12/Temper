"""Bare DeepSeek baseline runner — same questions, no harness context.

In CLOUD_OFFLINE mode returns canned answers without calling the API.
"""

import json
import time

from config import CLOUD_OFFLINE, DEEPSEEK_API_KEY, DEEPSEEK_MODEL

_OFFLINE_ANSWER = (
    "I can help with that. Could you please provide more details "
    "so I can assist you further?"
)


def run_baseline(questions: list[dict]) -> dict[str, dict]:
    """Run all questions through bare DeepSeek (no harness context).

    Returns {question_id: {answer, latency_ms}}.
    """
    if CLOUD_OFFLINE:
        return {
            q["question_id"]: {"answer": _OFFLINE_ANSWER, "latency_ms": 410}
            for q in questions
        }

    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set and CLOUD_OFFLINE is not true")

    from openai import OpenAI
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

    results = {}
    for q in questions:
        t0 = time.monotonic()
        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": q["prompt"]}],
                temperature=0,
            )
            answer = response.choices[0].message.content or ""
        except Exception as exc:
            print(f"[baseline] DeepSeek failed for {q['question_id']}: {exc}")
            answer = _OFFLINE_ANSWER
        latency_ms = int((time.monotonic() - t0) * 1000)
        results[q["question_id"]] = {"answer": answer, "latency_ms": latency_ms}

    return results


def run_single(question: dict) -> dict:
    """Run one question through bare DeepSeek. Returns {answer, latency_ms, input_tokens, output_tokens}."""
    if CLOUD_OFFLINE:
        return {"answer": _OFFLINE_ANSWER, "latency_ms": 410, "input_tokens": 0, "output_tokens": 0}

    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set and CLOUD_OFFLINE is not true")

    from openai import OpenAI
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

    t0 = time.monotonic()
    response = None
    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": question["prompt"]}],
            temperature=0,
        )
        answer = response.choices[0].message.content or ""
    except Exception as exc:
        print(f"[baseline] DeepSeek failed for {question['question_id']}: {exc}")
        answer = _OFFLINE_ANSWER
    latency_ms = int((time.monotonic() - t0) * 1000)
    usage = response.usage if response else None
    return {
        "answer": answer,
        "latency_ms": latency_ms,
        "input_tokens": usage.prompt_tokens if usage else 0,
        "output_tokens": usage.completion_tokens if usage else 0,
    }
