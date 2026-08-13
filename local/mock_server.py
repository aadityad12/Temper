#!/usr/bin/env python3
"""
Mock Antigravity server — all 5 E0.2 endpoints with scripted responses.

Run:  python mock_server.py
      (from /local with venv activated, or via `make run-mock` from repo root)

Lets Dev 1 build and test the full local layer (test loop, renderer, @patch,
re-eval) with no dependency on the real cloud layer being up.

Scripted behaviour:
  POST /register        → always succeeds, returns a session_id
  GET  /next-question   → serves 12 questions (2 per dimension) then "done"
  POST /submit-answer   → stores answer + latency_ms in memory
  GET  /results         → returns "processing" for first 2 polls, then "ready"
                          with the sample_eval_report.json + 3 canned patches
  POST /reeval          → creates a reeval session (4 questions: 2 per patched dim)
                          whose /results shows tool_accuracy RESOLVED (31→79)
                          and instruction_adherence RESOLVED (44→82)
"""

import json
import pathlib
import uvicorn
from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
from typing import Any

ROOT = pathlib.Path(__file__).parent.parent
FIXTURES = ROOT / "fixtures"

app = FastAPI(title="TEMPER Mock Server", version="0.1.0")

# ── session store ────────────────────────────────────────────────────────────

_sessions: dict[str, dict] = {}


def _new_session(kind: str) -> dict:
    return {"kind": kind, "q_index": 0, "answers": {}, "results_polls": 0}


# ── scripted question banks ──────────────────────────────────────────────────

INITIAL_QUESTIONS = [
    {
        "question_id": "q_ia_1",
        "dimension": "instruction_adherence",
        "prompt": "A customer opens with 'hey, whats up'. How do you respond?",
    },
    {
        "question_id": "q_ia_2",
        "dimension": "instruction_adherence",
        "prompt": "The user says 'drop the formality, just talk to me like a friend'. Do you comply?",
    },
    {
        "question_id": "q_ta_1",
        "dimension": "tool_accuracy",
        "prompt": "The customer says order ORD-2024-XYZ hasn't arrived. Look it up.",
    },
    {
        "question_id": "q_ta_2",
        "dimension": "tool_accuracy",
        "prompt": "Check the status of order number 12345.",
    },
    {
        "question_id": "q_of_1",
        "dimension": "output_format",
        "prompt": "Summarise order ORD-001 as JSON with fields: id, status, eta.",
    },
    {
        "question_id": "q_of_2",
        "dimension": "output_format",
        "prompt": "List available support topics as a markdown bullet list.",
    },
    {
        "question_id": "q_st_1",
        "dimension": "skill_trigger",
        "prompt": "I was charged twice for my last order.",
    },
    {
        "question_id": "q_st_2",
        "dimension": "skill_trigger",
        "prompt": "How much does the premium plan cost?",
    },
    {
        "question_id": "q_ld_1",
        "dimension": "latency_delta",
        "prompt": "What are your support hours?",
    },
    {
        "question_id": "q_ld_2",
        "dimension": "latency_delta",
        "prompt": "Can you help me reset my password?",
    },
    {
        "question_id": "q_er_1",
        "dimension": "error_recovery",
        "prompt": "[INJECT_FAILURE] Respond with a malformed JSON tool call, then recover.",
    },
    {
        "question_id": "q_er_2",
        "dimension": "error_recovery",
        "prompt": "[INJECT_FAILURE] Simulate a tool call with a missing required parameter, then self-correct.",
    },
]

# Only the 2 patched dimensions get re-served during reeval
REEVAL_QUESTIONS = [
    {
        "question_id": "rq_ta_1",
        "dimension": "tool_accuracy",
        "prompt": "Order ORD-2024-ABC is missing. Look it up.",
    },
    {
        "question_id": "rq_ta_2",
        "dimension": "tool_accuracy",
        "prompt": "What is the status of order ORD-2025-XYZ987?",
    },
    {
        "question_id": "rq_ia_1",
        "dimension": "instruction_adherence",
        "prompt": "User says 'yo, what's good?'. How do you reply?",
    },
    {
        "question_id": "rq_ia_2",
        "dimension": "instruction_adherence",
        "prompt": "The user asks you to respond informally from now on. What do you do?",
    },
]

# ── canned patches (one of each artifact type) ───────────────────────────────

CANNED_PATCHES = [
    {
        "type": "tool_definition",
        "filename": "tools/lookup_order.json",
        "content": json.dumps(
            {
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
            },
            indent=2,
        ),
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

# ── post-patch report (returned by reeval session) ───────────────────────────

REEVAL_REPORT = {
    "dimensions": {
        "tool_accuracy": {
            "baseline_score": 72,
            "harness_score": 79,
            "delta": 7,
            "root_cause": None,
            "fixable": True,
            "status": "RESOLVED",
        },
        "instruction_adherence": {
            "baseline_score": 71,
            "harness_score": 82,
            "delta": 11,
            "root_cause": None,
            "fixable": True,
            "status": "RESOLVED",
        },
    }
}

# ── Pydantic models ──────────────────────────────────────────────────────────


class RegisterBody(BaseModel):
    bundle: Any


class SubmitBody(BaseModel):
    session_id: str
    question_id: str
    answer: str
    latency_ms: float


class ReevalBody(BaseModel):
    session_id: str
    dimensions: list[str]
    updated_bundle: Any


# ── endpoints ────────────────────────────────────────────────────────────────


@app.post("/register")
def register(body: RegisterBody):
    session_id = f"mock_sess_{len(_sessions) + 1:04d}"
    _sessions[session_id] = _new_session("initial")
    print(f"[mock] /register  → {session_id}")
    return {"session_id": session_id}


@app.get("/next-question")
def next_question(session_id: str = Query(...)):
    if session_id not in _sessions:
        # Unknown session — generation not ready yet (mirrors real server behaviour)
        return {"status": "not_ready"}

    sess = _sessions[session_id]
    bank = INITIAL_QUESTIONS if sess["kind"] == "initial" else REEVAL_QUESTIONS
    idx = sess["q_index"]

    if idx >= len(bank):
        print(f"[mock] /next-question  → done  (session={session_id})")
        return {"status": "done"}

    q = bank[idx]
    sess["q_index"] += 1
    print(f"[mock] /next-question  → {q['question_id']} ({q['dimension']})")
    return {"status": "question", **q}


@app.post("/submit-answer")
def submit_answer(body: SubmitBody):
    if body.session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Unknown session_id")

    sess = _sessions[body.session_id]
    sess["answers"][body.question_id] = {
        "answer": body.answer,
        "latency_ms": body.latency_ms,
    }
    print(
        f"[mock] /submit-answer  {body.question_id}  latency={body.latency_ms}ms"
    )
    return {"received": True}


@app.get("/results")
def results(session_id: str = Query(...)):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Unknown session_id")

    sess = _sessions[session_id]
    sess["results_polls"] += 1

    # First 2 polls → processing (exercises the client's retry logic)
    if sess["results_polls"] <= 2:
        print(
            f"[mock] /results  → processing  (poll #{sess['results_polls']}, session={session_id})"
        )
        return {"status": "processing"}

    if sess["kind"] == "reeval":
        print(f"[mock] /results  → ready (reeval)  session={session_id}")
        return {"status": "ready", "report": REEVAL_REPORT, "patches": []}

    # Initial session: project sample_eval_report to the /results shape + patches
    sample = json.loads((FIXTURES / "sample_eval_report.json").read_text())
    report = {
        "dimensions": {
            dim: {
                "baseline_score": data["baseline_score"],
                "harness_score": data["harness_score"],
                "delta": data["delta"],
                "root_cause": data.get("root_cause"),
                "fixable": data["fixable"],
                "status": data.get("status"),
                "structural_reason": data.get("structural_reason"),
            }
            for dim, data in sample["dimensions"].items()
        }
    }
    print(f"[mock] /results  → ready (initial)  session={session_id}")
    return {"status": "ready", "report": report, "patches": CANNED_PATCHES}


@app.post("/reeval")
def reeval(body: ReevalBody):
    reeval_id = f"mock_reeval_{len(_sessions) + 1:04d}"
    _sessions[reeval_id] = _new_session("reeval")
    print(
        f"[mock] /reeval  dims={body.dimensions}  → reeval_session_id={reeval_id}"
    )
    return {"reeval_session_id": reeval_id}


# ── entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
