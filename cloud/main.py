#!/usr/bin/env python3
"""TEMPER cloud server — FastAPI implementation.

Original endpoints (backwards-compatible):
  POST /register, GET /next-question, POST /submit-answer, GET /results, POST /reeval

Pi room endpoints (new):
  POST /rooms/create            → room_id, join_token, dashboard_key, dashboard_url, connection_block
  POST /register                → also accepts {room_id, token, bundle} for Pi mode
  GET  /rooms/{room_id}/stream  → SSE stream for dashboard, authorized by dashboard_key
  GET  /rooms/{room_id}/state   → current room state for initial render, authorized by dashboard_key

Run:
  python main.py                        # live mode
  CLOUD_OFFLINE=true python main.py    # scripted offline mode
  make run-cloud                        # convenience alias

Port: CLOUD_PORT env var (default 8001).
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config  # noqa: F401
from config import CLOUD_OFFLINE, DEEPSEEK_MODEL, GEMINI_MODEL, HOST_URL, PORT
from session import (
    S_AWAITING, S_GENERATING, S_JUDGING, S_READY, S_REGISTERED,
    Question, Room, Session,
    bind_session_to_room, create_room, create_session, get_room,
    get_room_for_session, get_session,
)

app = FastAPI(title="TEMPER Cloud Server", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[HOST_URL, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic models ───────────────────────────────────────────────────────────

class RegisterBody(BaseModel):
    # Legacy path: bundle-based
    bundle: Any = None
    # Pi path: room_id + one-time join token
    room_id: str | None = None
    token: str | None = None
    # Set to true to run the coding benchmark instead of dimension-based eval
    bench: bool = False


class SubmitBody(BaseModel):
    session_id: str
    question_id: str
    answer: str
    latency_ms: float
    # Optional self-reported token usage from Pi
    input_tokens: int | None = None
    output_tokens: int | None = None


class ReevalBody(BaseModel):
    session_id: str
    dimensions: list[str]
    updated_bundle: Any


# ── helpers ───────────────────────────────────────────────────────────────────

def _require_session(session_id: str) -> Session:
    sess = get_session(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail=f"Unknown session_id: {session_id}")
    return sess


def _require_dashboard_room(room_id: str, key: str) -> Room:
    room = get_room(room_id)
    if room is None or room.dashboard_key != key:
        raise HTTPException(status_code=403, detail="Invalid room_id or dashboard key")
    return room


def _require_join_room(room_id: str, token: str) -> Room:
    room = get_room(room_id)
    if room is None or room.join_token != token:
        raise HTTPException(status_code=403, detail="Invalid room_id or join token")
    if room.join_token_used:
        raise HTTPException(status_code=409, detail="Join token already used")
    return room


def _has_bundle_content(bundle: Any) -> bool:
    if not isinstance(bundle, dict):
        return False
    return bool(bundle.get("system_prompt") or bundle.get("skills") or bundle.get("tools"))


ALL_DIMENSIONS = [
    "instruction_adherence", "tool_accuracy", "output_format",
    "skill_trigger", "latency_delta", "error_recovery",
]


def _connection_block(room_id: str, join_token: str, bench: bool = False) -> str:
    base = HOST_URL
    bench_field = '\n  "bench": true,' if bench else ""
    return f"""You are being evaluated by TEMPER. Follow these steps exactly.

STEP 1 — Build your environment bundle.
Collect the instructions, skills, and tools you are actually using into this shape:
{{
  "system_prompt": "<your active system/developer instructions, or null>",
  "skills": [{{"name": "<skill-name>", "content": "<skill markdown>"}}],
  "tools": [{{"name": "<tool-name>", "definition": {{}}}}]
}}

STEP 2 — Register once:
POST {base}/register
Body: {{{bench_field}
  "room_id": "{room_id}",
  "token": "{join_token}",
  "bundle": <the environment bundle from step 1>
}}
→ Save the "session_id" from the response.

STEP 3 — Loop until done:
  a. GET {base}/next-question?session_id=<session_id>
     If response has "status": "done" → stop.

  b. Answer the question using your normal capabilities.

  c. POST {base}/submit-answer
     Body: {{
       "session_id": "<session_id>",
       "question_id": "<question_id from step a>",
       "answer": "<your answer>",
       "latency_ms": <milliseconds you took to answer>,
       "input_tokens": <optional: your input token count>,
       "output_tokens": <optional: your output token count>
     }}

  d. Repeat from step a.

STEP 4 — You are done. TEMPER will generate your report automatically."""


# ── batch pipeline (original local/eval.py path) ─────────────────────────────

async def _run_pipeline(sess: Session) -> None:
    """Generate questions, run batch baseline, await harness answers, judge, patch."""
    loop = asyncio.get_event_loop()

    # 1. Generate questions
    try:
        from generator import generate_questions
        dims = sess.reeval_dimensions if sess.kind == "reeval" else ALL_DIMENSIONS
        raw_qs = await loop.run_in_executor(None, generate_questions, sess.bundle, dims)
        sess.questions = [Question(**q) for q in raw_qs]
        print(f"[pipeline] {sess.session_id}: generated {len(sess.questions)} questions")
    except Exception as exc:
        print(f"[pipeline] question generation failed: {exc}")
        sess.status = S_READY
        return

    # 2. Run batch baseline (non-Pi mode only)
    try:
        from baseline import run_baseline
        baseline_results = await loop.run_in_executor(None, run_baseline, raw_qs)
        for q in sess.questions:
            b = baseline_results.get(q.question_id)
            if b:
                q.baseline_answer = b["answer"]
                q.baseline_latency_ms = b.get("latency_ms")
    except Exception as exc:
        print(f"[pipeline] baseline failed: {exc}")

    # 3. Questions ready for harness answers
    sess.status = S_AWAITING
    print(f"[pipeline] {sess.session_id}: awaiting harness answers")

    # 4. Wait until all harness answers are in
    while not sess.all_answered():
        await asyncio.sleep(0.5)

    # 5. Judge
    sess.status = S_JUDGING
    print(f"[pipeline] {sess.session_id}: judging")
    try:
        from judge import judge_all
        dims = sess.reeval_dimensions if sess.kind == "reeval" else None
        dims_result = await loop.run_in_executor(
            None, judge_all, sess.questions, sess.bundle, dims, sess.kind == "reeval"
        )
        sess.report = {"dimensions": dims_result}
    except Exception as exc:
        print(f"[pipeline] judging failed: {exc}")
        sess.report = {"dimensions": {}}

    # 6. Generate patches (initial sessions only)
    if sess.kind == "initial":
        try:
            from patcher import generate_patches
            sess.patches = await loop.run_in_executor(
                None, generate_patches, sess.report["dimensions"], sess.bundle
            )
            print(f"[pipeline] {sess.session_id}: generated {len(sess.patches)} patches")
        except Exception as exc:
            print(f"[pipeline] patch generation failed: {exc}")

    sess.status = S_READY
    print(f"[pipeline] {sess.session_id}: ready")


# ── Pi per-question pipeline ──────────────────────────────────────────────────

async def _pi_generate_questions(sess: Session, room: Room) -> None:
    """Generate questions for a Pi session, then mark awaiting."""
    loop = asyncio.get_event_loop()

    if sess.bench_mode:
        from bench import BENCH_QUESTIONS
        sess.questions = [Question(**q) for q in BENCH_QUESTIONS]
        print(f"[pi-pipeline] {sess.session_id}: bench mode — {len(sess.questions)} question(s)")
    else:
        try:
            from generator import generate_questions
            raw_qs = await loop.run_in_executor(None, generate_questions, sess.bundle, ALL_DIMENSIONS)
            sess.questions = [Question(**q) for q in raw_qs]
            print(f"[pi-pipeline] {sess.session_id}: generated {len(sess.questions)} questions")
        except Exception as exc:
            print(f"[pi-pipeline] question generation failed: {exc}")
            sess.questions = []

    sess.status = S_AWAITING
    await room.push({
        "type": "questions_ready",
        "questions": [
            {"question_id": q.question_id, "dimension": q.dimension, "prompt": q.prompt}
            for q in sess.questions
        ],
    })


async def _process_single_question(sess: Session, room: Room, question: Question) -> None:
    """Parallel baseline + judge for one Pi question, then push SSE event."""
    loop = asyncio.get_event_loop()

    # 1. Push pi_submitted immediately so dashboard shows latency/tokens right away
    await room.push({
        "type": "pi_submitted",
        "question_id": question.question_id,
        "dimension": question.dimension,
        "latency_ms": question.harness_latency_ms,
        "input_tokens": question.pi_input_tokens,
        "output_tokens": question.pi_output_tokens,
    })

    # 2. Run baseline for this question
    try:
        from baseline import run_single
        b = await loop.run_in_executor(
            None, run_single,
            {"question_id": question.question_id, "prompt": question.prompt}
        )
        question.baseline_answer = b["answer"]
        question.baseline_latency_ms = b.get("latency_ms")
        question.baseline_input_tokens = b.get("input_tokens")
        question.baseline_output_tokens = b.get("output_tokens")
    except Exception as exc:
        print(f"[pi-pipeline] baseline failed for {question.question_id}: {exc}")
        question.baseline_answer = ""

    # 3. Judge Pi vs baseline
    try:
        if sess.bench_mode:
            from bench import judge_bench
            result = await loop.run_in_executor(
                None, judge_bench, question.harness_answer or "", question.baseline_answer or ""
            )
        else:
            from judge import judge_single_question
            result = await loop.run_in_executor(None, judge_single_question, question, sess.bundle)
    except Exception as exc:
        print(f"[pi-pipeline] judge failed for {question.question_id}: {exc}")
        result = {"baseline_score": 0, "harness_score": 0, "verdict": "Judgment unavailable."}

    # Cache result so all_judged() recognises this question as done (covers fallback too)
    question.judge_result = result

    # 4. Push question_judged SSE event
    await room.push({
        "type": "question_judged",
        "question_id": question.question_id,
        "dimension": question.dimension,
        "baseline_score": result["baseline_score"],
        "harness_score": result["harness_score"],
        "delta": result["harness_score"] - result["baseline_score"],
        "verdict": result["verdict"],
        "pi_latency_ms": question.harness_latency_ms,
        "baseline_latency_ms": question.baseline_latency_ms,
        "pi_input_tokens": question.pi_input_tokens,
        "pi_output_tokens": question.pi_output_tokens,
        "baseline_input_tokens": question.baseline_input_tokens,
        "baseline_output_tokens": question.baseline_output_tokens,
    })

    # 5. Auto-finalize when all questions are judged
    if sess.all_judged():
        await _pi_finalize(sess, room)


async def _pi_finalize(sess: Session, room: Room) -> None:
    """Aggregate results + generate patches, then push session_complete."""
    loop = asyncio.get_event_loop()
    sess.status = S_JUDGING

    if sess.bench_mode:
        q = sess.questions[0]
        r = q.judge_result or {"baseline_score": 0, "harness_score": 0, "verdict": ""}
        delta = r["harness_score"] - r["baseline_score"]
        sess.report = {
            "dimensions": {
                "coding_bench": {
                    "baseline_score": r["baseline_score"],
                    "harness_score": r["harness_score"],
                    "delta": delta,
                    "verdict": r.get("verdict", ""),
                    "status": "PASSING" if delta >= 0 else "NEEDS_PATCH",
                }
            }
        }
        sess.patches = []
        sess.status = S_READY
        print(f"[pi-pipeline] {sess.session_id}: bench complete")
        await room.push({"type": "session_complete", "report": sess.report, "patches": []})
        return

    try:
        from judge import judge_all
        dims_result = await loop.run_in_executor(
            None, judge_all, sess.questions, sess.bundle, None, False
        )
        sess.report = {"dimensions": dims_result}
    except Exception as exc:
        print(f"[pi-pipeline] final aggregation failed: {exc}")
        sess.report = {"dimensions": {}}

    try:
        from patcher import generate_patches
        sess.patches = await loop.run_in_executor(
            None, generate_patches, sess.report["dimensions"], sess.bundle
        )
    except Exception as exc:
        print(f"[pi-pipeline] patch generation failed: {exc}")

    sess.status = S_READY
    print(f"[pi-pipeline] {sess.session_id}: complete")

    await room.push({
        "type": "session_complete",
        "report": sess.report,
        "patches": sess.patches,
    })


# ── static UI ─────────────────────────────────────────────────────────────────

_UI_DIST = Path(__file__).parent.parent / "extension" / "ui" / "dist"


# ── endpoints ─────────────────────────────────────────────────────────────────

# SPA fallback — serves index.html for /room/<id> so dashboard reloads don't 404
@app.get("/room/{room_id}", include_in_schema=False)
async def spa_room(room_id: str):
    index = _UI_DIST / "index.html"
    if index.exists():
        return FileResponse(str(index))
    raise HTTPException(status_code=404, detail="UI not built — run: make build-ui")


# ── Pi room endpoints ─────────────────────────────────────────────────────────

@app.post("/rooms/create")
async def rooms_create(bench: bool = Query(False)):
    room = create_room()
    dash_url = f"{HOST_URL}/room/{room.room_id}?key={room.dashboard_key}"
    block = _connection_block(room.room_id, room.join_token, bench)
    print(f"[/rooms/create] room_id={room.room_id}")
    return {
        "room_id": room.room_id,
        "join_token": room.join_token,
        "dashboard_key": room.dashboard_key,
        # Backwards-compatible alias for older copy/paste clients.
        "token": room.join_token,
        "dashboard_url": dash_url,
        "connection_block": block,
    }


@app.get("/rooms/{room_id}/state")
async def room_state(room_id: str, key: str = Query(...)):
    room = _require_dashboard_room(room_id, key)
    sess = get_session(room.session_id) if room.session_id else None

    questions_data = []
    if sess:
        for q in sess.questions:
            questions_data.append({
                "question_id": q.question_id,
                "dimension": q.dimension,
                "prompt": q.prompt,
                "pi_latency_ms": q.harness_latency_ms,
                "pi_input_tokens": q.pi_input_tokens,
                "pi_output_tokens": q.pi_output_tokens,
                "baseline_latency_ms": q.baseline_latency_ms,
                "baseline_input_tokens": q.baseline_input_tokens,
                "baseline_output_tokens": q.baseline_output_tokens,
                "judge_result": q.judge_result,
            })

    return {
        "room_id": room_id,
        "pi_connected": room.session_id is not None,
        "status": sess.status if sess else "waiting",
        "questions": questions_data,
        "report": sess.report if sess else None,
        "patches": sess.patches if sess else [],
        "baseline_model": DEEPSEEK_MODEL,
        "judge_model": GEMINI_MODEL,
    }


@app.get("/rooms/{room_id}/stream")
async def room_stream(room_id: str, key: str = Query(...)):
    room = _require_dashboard_room(room_id, key)

    async def event_generator():
        queue = room.add_subscriber()
        try:
            # Send initial ping so client knows it's connected
            yield "data: " + json.dumps({"type": "connected", "room_id": room_id}) + "\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield "data: " + json.dumps(event) + "\n\n"
                except asyncio.TimeoutError:
                    # Keepalive ping
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            room.remove_subscriber(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── original endpoints (backwards-compatible) ─────────────────────────────────

@app.post("/register")
async def register(body: RegisterBody):
    # Pi path: room_id + token
    if body.room_id and body.token:
        room = _require_join_room(body.room_id, body.token)
        if room.session_id:
            raise HTTPException(status_code=409, detail="Room already registered")
        if not _has_bundle_content(body.bundle):
            raise HTTPException(status_code=400, detail="Pi registration requires an environment bundle")

        room.join_token_used = True
        sess = create_session(bundle=body.bundle, pi_mode=True)
        sess.bench_mode = body.bench
        room.session_id = sess.session_id
        bind_session_to_room(sess.session_id, room.room_id)
        sess.status = S_GENERATING

        # Push event so dashboard knows Pi connected
        asyncio.create_task(room.push({"type": "pi_connected"}))
        # Generate questions in background
        asyncio.create_task(_pi_generate_questions(sess, room))

        print(f"[/register] Pi mode → room={body.room_id} session={sess.session_id}")
        return {"session_id": sess.session_id}

    # Legacy path: bundle-based
    if body.bundle is None:
        raise HTTPException(status_code=400, detail="Provide either bundle or room_id+token")
    sess = create_session(body.bundle)
    sess.status = S_GENERATING
    asyncio.create_task(_run_pipeline(sess))
    print(f"[/register] bundle mode → {sess.session_id}")
    return {"session_id": sess.session_id}


@app.get("/next-question")
async def next_question(session_id: str = Query(...)):
    sess = _require_session(session_id)

    if sess.status == S_GENERATING:
        return {"status": "not_ready"}

    q = sess.next_question()
    if q is None:
        return {"status": "done"}

    print(f"[/next-question] {sess.session_id} → {q.question_id} ({q.dimension})")
    return {
        "status": "question",
        "question_id": q.question_id,
        "dimension": q.dimension,
        "prompt": q.prompt,
    }


@app.post("/submit-answer")
async def submit_answer(body: SubmitBody):
    sess = _require_session(body.session_id)
    question = sess.record_harness_answer(
        body.question_id, body.answer, body.latency_ms,
        body.input_tokens, body.output_tokens,
    )
    if question is None:
        raise HTTPException(status_code=404, detail=f"Unknown question_id: {body.question_id}")

    print(f"[/submit-answer] {body.session_id}/{body.question_id} latency={body.latency_ms}ms")

    # Pi mode: trigger per-question baseline + judge in background
    if sess.pi_mode:
        room = get_room_for_session(body.session_id)
        if room:
            asyncio.create_task(_process_single_question(sess, room, question))

    return {"received": True}


@app.get("/results")
async def results(session_id: str = Query(...)):
    sess = _require_session(session_id)

    if sess.status != S_READY:
        return {"status": "processing"}

    print(f"[/results] {session_id} → ready")
    return {
        "status": "ready",
        "report": sess.report,
        "patches": sess.patches,
    }


@app.post("/reeval")
async def reeval(body: ReevalBody):
    _require_session(body.session_id)
    sess = create_session(
        bundle=body.updated_bundle,
        kind="reeval",
        parent_session_id=body.session_id,
        reeval_dimensions=body.dimensions,
    )
    sess.status = S_GENERATING
    asyncio.create_task(_run_pipeline(sess))
    print(f"[/reeval] dims={body.dimensions} → {sess.session_id}")
    return {"reeval_session_id": sess.session_id}


# ── static UI (served last so API routes take priority) ───────────────────────

@app.on_event("startup")
async def _mount_ui():
    if _UI_DIST.exists():
        app.mount("/", StaticFiles(directory=str(_UI_DIST), html=True), name="ui")
        print(f"[temper-cloud] Serving UI from {_UI_DIST}")
    else:
        print(f"[temper-cloud] No UI dist found at {_UI_DIST} — run: make build-ui")

        @app.get("/")
        async def _no_ui():
            return {"message": "UI not built. Run: make build-ui", "api_docs": "/docs"}


# ── entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mode = "OFFLINE" if CLOUD_OFFLINE else "LIVE"
    print(f"[temper-cloud] Starting in {mode} mode on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, reload=False)
