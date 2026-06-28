"""HTTP client for all 5 TEMPER API endpoints with retry/backoff logic."""

import os
import time
import httpx
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

OFFLINE = os.getenv("TEMPER_OFFLINE", "").lower() == "true"
_BASE = os.getenv("ANTIGRAVITY_BASE_URL", "http://localhost:8000")
BASE_URL = "http://localhost:8000" if OFFLINE else _BASE

_MAX_HTTP_RETRIES = 3
_HTTP_RETRY_DELAY = 2


def _http(fn):
    """Retry up to 3 times on network / server errors (5xx)."""
    delay = _HTTP_RETRY_DELAY
    last_exc = None
    for attempt in range(_MAX_HTTP_RETRIES):
        try:
            resp = fn()
            if resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"Server error {resp.status_code}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            return resp
        except (httpx.NetworkError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt < _MAX_HTTP_RETRIES - 1:
                print(f"  [http] error ({exc}) — retry in {delay}s")
                time.sleep(delay)
                delay = min(delay * 2, 10)
    raise last_exc


def register(bundle: dict) -> str:
    resp = _http(lambda: httpx.post(f"{BASE_URL}/register", json={"bundle": bundle}, timeout=30))
    return resp.json()["session_id"]


def next_question(session_id: str) -> dict:
    """Poll /next-question, backing off on not_ready. Returns question or {status:'done'}."""
    delay = 2
    poll = 0
    while True:
        resp = _http(lambda: httpx.get(
            f"{BASE_URL}/next-question", params={"session_id": session_id}, timeout=30
        ))
        data = resp.json()
        if data["status"] != "not_ready":
            return data
        poll += 1
        print(f"  [poll] not_ready (#{poll}) — retrying in {delay}s")
        time.sleep(delay)
        delay = min(delay * 2, 10)


def submit_answer(session_id: str, question_id: str, answer: str, latency_ms: int) -> None:
    _http(lambda: httpx.post(
        f"{BASE_URL}/submit-answer",
        json={"session_id": session_id, "question_id": question_id,
              "answer": answer, "latency_ms": latency_ms},
        timeout=30,
    ))


def get_results(session_id: str) -> dict:
    """Poll /results until status == 'ready'."""
    delay = 3
    poll = 0
    while True:
        resp = _http(lambda: httpx.get(
            f"{BASE_URL}/results", params={"session_id": session_id}, timeout=30
        ))
        data = resp.json()
        if data["status"] == "ready":
            return data
        poll += 1
        print(f"  [poll] results processing (#{poll}) — retrying in {delay}s")
        time.sleep(delay)
        delay = min(delay * 2, 15)


def reeval(session_id: str, dimensions: list, updated_bundle: dict) -> str:
    resp = _http(lambda: httpx.post(
        f"{BASE_URL}/reeval",
        json={"session_id": session_id, "dimensions": dimensions, "updated_bundle": updated_bundle},
        timeout=30,
    ))
    return resp.json()["reeval_session_id"]
