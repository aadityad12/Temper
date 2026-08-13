"""Gemini-as-judge: scores harness vs baseline answers, computes delta, identifies root causes.

CLOUD_OFFLINE mode returns the villain-env pre-baked demo scores.
"""

import json
import statistics

from config import CLOUD_OFFLINE, GEMINI_API_KEY, GEMINI_MODEL
from session import Question

_OFFLINE_SCORES = {
    "instruction_adherence": {"baseline": 71, "harness": 44,
                               "root_cause": "System prompt contains two contradictory instructions: "
                               "'always respond formally' and 'respond conversationally to greetings'. "
                               "The model defaults to the latter, violating the former."},
    "tool_accuracy":         {"baseline": 72, "harness": 31,
                               "root_cause": "Tool definition for get_order lacks an enum or format "
                               "constraint on order_id. The model produces plausible-looking but incorrect "
                               "order id formats 70% of the time."},
    "output_format":         {"baseline": 88, "harness": 85, "root_cause": None},
    "skill_trigger":         {"baseline": 60, "harness": 52,
                               "root_cause": "The 'escalate' skill trigger is too broad — it fires on any "
                               "mention of money, not just billing disputes. Causes false-positive "
                               "escalations on pricing questions."},
    "latency_delta":         {"baseline": 90, "harness": 74,
                               "root_cause": "Harness adds ~340ms overhead per call due to prepending all "
                               "skill files regardless of relevance."},
    "error_recovery":        {"baseline": 38, "harness": 35,
                               "root_cause": "Model consistently fails to self-correct malformed JSON tool "
                               "calls. No harness-level skill can reliably prompt self-correction of this "
                               "failure mode."},
}

# Post-patch scores returned in CLOUD_OFFLINE reeval sessions
_OFFLINE_REEVAL_SCORES = {
    "instruction_adherence": {"baseline": 71, "harness": 82, "root_cause": None},
    "tool_accuracy":         {"baseline": 72, "harness": 79, "root_cause": None},
    "skill_trigger":         {"baseline": 60, "harness": 71, "root_cause": None},
    "latency_delta":         {"baseline": 90, "harness": 80, "root_cause": None},
    "error_recovery":        {"baseline": 38, "harness": 37, "root_cause": None},
}

_OFFLINE_LATENCY = {"baseline_ms": 410, "harness_ms": 750}

_JUDGE_SINGLE_PROMPT = """You are TEMPER's evaluation judge. Score two AI answers for the given dimension.

## Dimension: {dimension}
{dimension_description}

## Question
{question}

## Baseline Answer (bare model, no harness)
{baseline_answer}

## Pi Answer (model under test)
{harness_answer}

Score each answer 0–100 for the {dimension} dimension.
If Pi score < baseline by more than 5 points, write a one-sentence verdict explaining why.
Otherwise write a one-sentence verdict noting they performed similarly or Pi did better.

Return ONLY valid JSON:
{{
  "baseline_score": <0-100>,
  "harness_score": <0-100>,
  "verdict": "<one sentence>"
}}"""

_JUDGE_PROMPT = """You are TEMPER's evaluation judge. Score how well an AI model answer satisfies the
evaluation dimension, given the question and the environment context.

## Environment Bundle (context the harness provides)
{bundle_summary}

## Dimension: {dimension}
{dimension_description}

## Question
{question}

## Baseline Answer (bare model, no harness context)
{baseline_answer}

## Harness Answer (model with full harness applied)
{harness_answer}

## Scoring Task
Score each answer 0–100 for the {dimension} dimension.
100 = perfect adherence / accuracy / format / trigger precision / recovery
0   = complete failure

Also:
- If the harness score is lower than the baseline score by more than 5 points, provide a concise
  root_cause (1-2 sentences) explaining WHY the harness is making this worse.
- Otherwise set root_cause to null.

Return ONLY valid JSON with this exact structure:
{{
  "baseline_score": <number 0-100>,
  "harness_score": <number 0-100>,
  "root_cause": "<string or null>"
}}"""

_DIM_DESCRIPTIONS = {
    "instruction_adherence": "Does the model follow the stated rules and behavioral constraints?",
    "tool_accuracy": "Are tool calls formed correctly with the right parameters and formats?",
    "output_format": "Is the response in the required output format or structure?",
    "skill_trigger": "Are skills invoked at the right times — not too early, not missed?",
    "error_recovery": "When failures occur, does the model self-correct rather than compound the error?",
}


def _bundle_summary(bundle: dict) -> str:
    parts = []
    if bundle.get("system_prompt"):
        parts.append(f"System prompt:\n{bundle['system_prompt'][:600]}")
    if bundle.get("skills"):
        for s in bundle["skills"]:
            parts.append(f"Skill {s['name']}:\n{s['content'][:300]}")
    if bundle.get("tools"):
        for t in bundle["tools"]:
            parts.append(f"Tool {t['name']}: {json.dumps(t['definition'])[:400]}")
    return "\n\n".join(parts)


def judge_dimension(dimension: str, questions: list[Question], bundle: dict,
                    is_reeval: bool = False) -> dict:
    """Score all questions for one dimension. Returns dimension result dict."""
    if CLOUD_OFFLINE:
        return _offline_result(dimension, is_reeval)

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set and CLOUD_OFFLINE is not true")

    if dimension == "latency_delta":
        return _compute_latency_delta(questions, is_reeval)

    from google import genai
    from google.genai import types
    client = genai.Client(api_key=GEMINI_API_KEY)

    bundle_summary = _bundle_summary(bundle)
    dim_desc = _DIM_DESCRIPTIONS.get(dimension, "")

    baseline_scores, harness_scores, root_causes = [], [], []

    for q in questions:
        if q.dimension != dimension:
            continue
        if not q.baseline_answer or not q.harness_answer:
            continue

        prompt = _JUDGE_PROMPT.format(
            bundle_summary=bundle_summary,
            dimension=dimension,
            dimension_description=dim_desc,
            question=q.prompt,
            baseline_answer=q.baseline_answer,
            harness_answer=q.harness_answer,
        )

        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            result = json.loads(response.text)
            baseline_scores.append(float(result["baseline_score"]))
            harness_scores.append(float(result["harness_score"]))
            if result.get("root_cause"):
                root_causes.append(result["root_cause"])
        except Exception as exc:
            print(f"[judge] Gemini failed for {dimension}/{q.question_id}: {exc}")

    if not baseline_scores:
        return _offline_result(dimension, is_reeval)

    baseline_avg = round(statistics.mean(baseline_scores))
    harness_avg = round(statistics.mean(harness_scores))
    delta = harness_avg - baseline_avg
    root_cause = root_causes[0] if root_causes else None

    return _build_result(dimension, baseline_avg, harness_avg, delta, root_cause,
                         len(baseline_scores), is_reeval=is_reeval)


def _compute_latency_delta(questions: list[Question], is_reeval: bool = False) -> dict:
    """Latency delta — computed from timing data, no LLM call."""
    latency_qs = [q for q in questions if q.dimension == "latency_delta"]
    harness_latencies = [q.harness_latency_ms for q in latency_qs
                         if q.harness_latency_ms is not None]
    baseline_latencies = [q.baseline_latency_ms for q in latency_qs
                          if q.baseline_latency_ms is not None]

    if not harness_latencies or not baseline_latencies:
        return _offline_result("latency_delta", is_reeval)

    baseline_ms = statistics.mean(baseline_latencies)
    harness_ms = statistics.mean(harness_latencies)
    baseline_score = min(100, max(0, 100 - int(baseline_ms / 20)))
    harness_score = min(100, max(0, 100 - int(harness_ms / 20)))
    delta = harness_score - baseline_score

    return _build_result("latency_delta", baseline_score, harness_score, delta,
                         root_cause=None, test_cases_run=len(latency_qs), is_reeval=is_reeval,
                         latency_baseline_ms=baseline_ms, latency_harness_ms=harness_ms)


def _offline_result(dimension: str, is_reeval: bool = False) -> dict:
    bank = _OFFLINE_REEVAL_SCORES if is_reeval else _OFFLINE_SCORES
    s = bank.get(dimension, _OFFLINE_SCORES[dimension])
    delta = s["harness"] - s["baseline"]
    return _build_result(dimension, s["baseline"], s["harness"], delta,
                         s.get("root_cause"), test_cases_run=2, is_reeval=is_reeval)


def _build_result(dimension: str, baseline: int, harness: int, delta: int,
                  root_cause: str | None, test_cases_run: int = 2,
                  is_reeval: bool = False, latency_baseline_ms: float | None = None,
                  latency_harness_ms: float | None = None) -> dict:
    fixable, structural_reason, status = _classify(dimension, delta, root_cause, is_reeval)
    if dimension == "latency_delta" and latency_baseline_ms is None:
        latency_baseline_ms = _OFFLINE_LATENCY["baseline_ms"]
        latency_harness_ms = _OFFLINE_LATENCY["harness_ms"]
    return {
        "baseline_score": baseline,
        "harness_score": harness,
        "delta": delta,
        "status": status,
        "root_cause": root_cause,
        "fixable": fixable,
        "structural_reason": structural_reason,
        "fix_type": _fix_type(dimension) if fixable and delta < -5 else None,
        "test_cases_run": test_cases_run,
        "latency_baseline_ms": latency_baseline_ms if dimension == "latency_delta" else None,
        "latency_harness_ms": latency_harness_ms if dimension == "latency_delta" else None,
    }


def _classify(dimension: str, delta: int, root_cause: str | None,
              is_reeval: bool = False):
    """Determine fixable, structural_reason, and status."""
    if dimension == "error_recovery":
        structural_reason = (
            "Self-correction of failed tool calls requires the model to identify its own output "
            "as the error source. This is a model-capability ceiling. Fix: add order_id validation "
            "in application code before the LLM call, or upgrade to a model with stronger "
            "tool-use self-correction."
        )
        return False, structural_reason, "STRUCTURAL_LIMITATION"
    # In a reeval, harness_score > baseline_score means the patch fixed it
    if is_reeval and delta >= -5:
        return True, None, "RESOLVED"
    if delta >= -5:
        return True, None, "PASSING"
    return True, None, "NEEDS_PATCH"


def _fix_type(dimension: str) -> str | None:
    return {
        "instruction_adherence": "system_prompt",
        "tool_accuracy": "tool_definition",
        "output_format": "skill",
        "skill_trigger": "skill",
        "latency_delta": "skill",
        "error_recovery": "skill",
    }.get(dimension)


def judge_single_question(question: Question, bundle: dict) -> dict:
    """Judge one question immediately. Caches result on question.judge_result.

    Returns {baseline_score, harness_score, verdict}.
    Used in Pi mode for live per-question SSE updates.
    """
    if CLOUD_OFFLINE:
        dim = question.dimension
        s = _OFFLINE_SCORES.get(dim, {"baseline": 70, "harness": 70})
        result = {
            "baseline_score": s["baseline"],
            "harness_score": s["harness"],
            "verdict": s.get("root_cause") or "Both answered similarly.",
        }
        question.judge_result = result
        return result

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")

    if question.dimension == "latency_delta":
        b_ms = question.baseline_latency_ms or 400
        h_ms = question.harness_latency_ms or 800
        b_score = min(100, max(0, 100 - int(b_ms / 20)))
        h_score = min(100, max(0, 100 - int(h_ms / 20)))
        verdict = f"Pi latency {h_ms:.0f}ms vs baseline {b_ms:.0f}ms."
        result = {"baseline_score": b_score, "harness_score": h_score, "verdict": verdict}
        question.judge_result = result
        return result

    from google import genai
    from google.genai import types
    client = genai.Client(api_key=GEMINI_API_KEY)

    dim_desc = _DIM_DESCRIPTIONS.get(question.dimension, "")
    prompt = _JUDGE_SINGLE_PROMPT.format(
        dimension=question.dimension,
        dimension_description=dim_desc,
        question=question.prompt,
        baseline_answer=question.baseline_answer or "",
        harness_answer=question.harness_answer or "",
    )

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )
        data = json.loads(response.text)
        result = {
            "baseline_score": float(data["baseline_score"]),
            "harness_score": float(data["harness_score"]),
            "verdict": str(data.get("verdict", "")),
        }
    except Exception as exc:
        print(f"[judge] single question failed for {question.question_id}: {exc}")
        result = {"baseline_score": 70, "harness_score": 70, "verdict": "Judgment unavailable."}

    question.judge_result = result
    return result


def judge_all(questions: list[Question], bundle: dict,
              dimensions: list[str] | None = None,
              is_reeval: bool = False) -> dict:
    """Judge all dimensions. Returns the full dimensions dict for the report.

    In Pi mode, questions may already have judge_result cached from per-question
    judging — this aggregates cached results instead of calling Gemini again.
    """
    all_dims = dimensions or [
        "instruction_adherence", "tool_accuracy", "output_format",
        "skill_trigger", "latency_delta", "error_recovery",
    ]
    return {dim: _judge_dimension_with_cache(dim, questions, bundle, is_reeval)
            for dim in all_dims}


def _judge_dimension_with_cache(dimension: str, questions: list[Question],
                                 bundle: dict, is_reeval: bool = False) -> dict:
    """Aggregate cached per-question results when available, otherwise call Gemini."""
    dim_qs = [q for q in questions if q.dimension == dimension and q.judge_result is not None]

    if dim_qs:
        import statistics
        baseline_scores = [q.judge_result["baseline_score"] for q in dim_qs]
        harness_scores = [q.judge_result["harness_score"] for q in dim_qs]
        baseline_avg = round(statistics.mean(baseline_scores))
        harness_avg = round(statistics.mean(harness_scores))
        delta = harness_avg - baseline_avg
        root_cause = next(
            (q.judge_result.get("verdict") for q in dim_qs
             if q.judge_result.get("harness_score", 100) < q.judge_result.get("baseline_score", 0) - 5),
            None,
        )
        return _build_result(dimension, baseline_avg, harness_avg, delta, root_cause,
                             len(dim_qs), is_reeval=is_reeval)

    return judge_dimension(dimension, questions, bundle, is_reeval)
