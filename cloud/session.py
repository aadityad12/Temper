"""Session store and state machine for TEMPER cloud server.

State lifecycle:
  registered → generating → awaiting_answers → judging → ready

Room lifecycle (Pi mode):
  room created → Pi registers → questions generated → per-Q pipeline → ready
"""

import asyncio
import secrets
import uuid
from dataclasses import dataclass, field
from typing import Any

# ── state constants ───────────────────────────────────────────────────────────

S_REGISTERED = "registered"
S_GENERATING = "generating"
S_AWAITING = "awaiting_answers"
S_JUDGING = "judging"
S_READY = "ready"


@dataclass
class Question:
    question_id: str
    dimension: str
    prompt: str
    baseline_answer: str | None = None
    baseline_latency_ms: float | None = None
    harness_answer: str | None = None
    harness_latency_ms: float | None = None
    pi_input_tokens: int | None = None
    pi_output_tokens: int | None = None
    baseline_input_tokens: int | None = None
    baseline_output_tokens: int | None = None
    # Cached per-question judge result (set after judge_single_question)
    judge_result: dict | None = None  # {baseline_score, harness_score, verdict}


@dataclass
class Session:
    session_id: str
    kind: str                              # "initial" | "reeval"
    parent_session_id: str | None         # reeval only
    reeval_dimensions: list[str]          # reeval only
    bundle: dict
    status: str = S_REGISTERED
    pi_mode: bool = False                 # True when session is from a Pi room
    bench_mode: bool = False              # True when running the coding benchmark

    questions: list[Question] = field(default_factory=list)
    q_cursor: int = 0                      # next question index to serve

    report: dict | None = None
    patches: list[dict] = field(default_factory=list)

    def next_question(self) -> Question | None:
        if self.q_cursor < len(self.questions):
            q = self.questions[self.q_cursor]
            self.q_cursor += 1
            return q
        return None

    def all_answered(self) -> bool:
        return all(q.harness_answer is not None for q in self.questions)

    def all_judged(self) -> bool:
        return (
            len(self.questions) > 0
            and all(q.judge_result is not None for q in self.questions)
        )

    def record_harness_answer(
        self,
        question_id: str,
        answer: str,
        latency_ms: float,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> Question | None:
        for q in self.questions:
            if q.question_id == question_id:
                q.harness_answer = answer
                q.harness_latency_ms = latency_ms
                q.pi_input_tokens = input_tokens
                q.pi_output_tokens = output_tokens
                return q
        return None


# ── room (Pi mode) ────────────────────────────────────────────────────────────

@dataclass
class Room:
    room_id: str
    join_token: str
    dashboard_key: str
    join_token_used: bool = False
    session_id: str | None = None          # set when Pi calls /register
    # SSE subscribers: list of asyncio.Queue (one per connected browser tab)
    _subscribers: list = field(default_factory=list)

    def add_subscriber(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def remove_subscriber(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def push(self, event: dict) -> None:
        for q in list(self._subscribers):
            await q.put(event)


# ── in-memory stores ──────────────────────────────────────────────────────────

_sessions: dict[str, Session] = {}
_rooms: dict[str, Room] = {}
_join_token_to_room: dict[str, str] = {}       # one-time join token → room_id
_dashboard_key_to_room: dict[str, str] = {}    # reusable dashboard key → room_id
_session_to_room_id: dict[str, str] = {}       # session_id → room_id


def create_session(
    bundle: dict,
    kind: str = "initial",
    parent_session_id: str | None = None,
    reeval_dimensions: list[str] | None = None,
    pi_mode: bool = False,
) -> Session:
    if kind == "reeval":
        sid = f"reeval_{uuid.uuid4().hex[:8]}"
    else:
        sid = f"sess_{uuid.uuid4().hex[:8]}"
    sess = Session(
        session_id=sid,
        kind=kind,
        parent_session_id=parent_session_id,
        reeval_dimensions=reeval_dimensions or [],
        bundle=bundle,
        pi_mode=pi_mode,
    )
    _sessions[sid] = sess
    return sess


def get_session(session_id: str) -> Session | None:
    return _sessions.get(session_id)


def create_room() -> Room:
    room_id = uuid.uuid4().hex[:12]
    join_token = secrets.token_urlsafe(24)
    dashboard_key = secrets.token_urlsafe(24)
    room = Room(room_id=room_id, join_token=join_token, dashboard_key=dashboard_key)
    _rooms[room_id] = room
    _join_token_to_room[join_token] = room_id
    _dashboard_key_to_room[dashboard_key] = room_id
    return room


def get_room(room_id: str) -> Room | None:
    return _rooms.get(room_id)


def bind_session_to_room(session_id: str, room_id: str) -> None:
    _session_to_room_id[session_id] = room_id


def get_room_for_session(session_id: str) -> Room | None:
    rid = _session_to_room_id.get(session_id)
    return _rooms.get(rid) if rid else None


def get_room_by_join_token(token: str) -> Room | None:
    rid = _join_token_to_room.get(token)
    return _rooms.get(rid) if rid else None


def get_room_by_dashboard_key(key: str) -> Room | None:
    rid = _dashboard_key_to_room.get(key)
    return _rooms.get(rid) if rid else None
