# TEMPER API Contract

Authoritative interface between the local/Pi client layer and the TEMPER cloud server. Do not change field names without updating both sides and bumping this doc.

---

## Communication model

The TEMPER cloud server is the **server**. Local scripts (`eval.py`, `patch.py`) and the Pi coding agent are **clients**. All traffic is outbound HTTP from client → server.

```
Client (local or Pi)         TEMPER Cloud Server
     │                              │
     │  POST /register  ──────────► │  creates session, starts
     │  ◄────────────── session_id  │  question generation + baseline
     │                              │
     │  GET /next-question ────────►│
     │  ◄──── {question} or {done} │  serves queue one at a time
     │                              │
     │  (client answers question)   │
     │                              │
     │  POST /submit-answer ───────►│  stores answer + latency
     │  ◄────────── {received:true} │
     │                              │
     │  ... repeat until done ...   │
     │                              │
     │  GET /results ──────────────►│  may return {processing} first
     │  ◄────── report + patches    │
     │                              │
     │  POST /reeval ──────────────►│  re-judge patched dims only
     │  ◄──── reeval_session_id     │
     │                              │
     │  GET /results?session_id=... │  same endpoint, new session id
     │  ◄──── updated report        │
```

**Pi room path** (additional endpoints for the live dashboard):

```
Dashboard browser            TEMPER Cloud Server
     │                              │
     │  POST /rooms/create ────────►│  issues room_id + tokens
     │  ◄── room_id, join_token,    │
     │       dashboard_key          │
     │                              │
     │  GET /rooms/{id}/stream ────►│  SSE: live question/score events
     │  GET /rooms/{id}/state ─────►│  snapshot for page reload
```

---

## Dimension enum

All dimension keys must use exactly these strings:

```
instruction_adherence
tool_accuracy
output_format
skill_trigger
latency_delta
error_recovery
```

---

## Endpoints

### POST /register

Ingests the environment bundle. Returns a session id immediately (question generation + baseline run start in background).

**Request**
```json
{
  "bundle": {
    "system_prompt": "string | null",
    "skills": [
      { "name": "string", "content": "string" }
    ],
    "tools": [
      { "name": "string", "definition": {} }
    ]
  },
  "room_id": "string (optional — Pi room path only)",
  "token":   "string (optional — one-time join token for Pi room)",
  "bench":   "boolean (optional — run coding benchmark instead of dimension eval)"
}
```

**Response 200**
```json
{ "session_id": "string" }
```

**Response 422** — schema-invalid bundle
```json
{ "error": "string" }
```

**Side effect:** server begins Gemini question generation and bare-DeepSeek baseline run in background. `/next-question` returns `{"status":"not_ready"}` until generation completes.

---

### GET /next-question

Returns the next unanswered question for a session.

**Request**
```
GET /next-question?session_id=<string>
```

**Response — question available**
```json
{
  "status": "question",
  "question_id": "string",
  "dimension": "<dimension enum>",
  "prompt": "string"
}
```

**Response — all questions answered**
```json
{ "status": "done" }
```

**Response — generation still running**
```json
{ "status": "not_ready" }
```

On `not_ready`: back off and retry (start at 2s, cap at 10s, exponential).

---

### POST /submit-answer

Submits the client's answer and measured latency for a question.

**Request**
```json
{
  "session_id":    "string",
  "question_id":   "string",
  "answer":        "string",
  "latency_ms":    1234,
  "input_tokens":  42,
  "output_tokens": 87
}
```

`input_tokens` and `output_tokens` are optional. When provided they appear in the dashboard token usage panel.

`latency_ms` measures inference time only (exclude prompt assembly). Must be included on every submission — the server uses it to compute the `latency_delta` dimension score.

**Response 200**
```json
{ "received": true }
```

Re-submitting the same `question_id` updates rather than duplicates (idempotent).

**Side effect:** when the last answer arrives, the server advances to `judging` (triggers Gemini evaluation). In Pi room mode it also pushes a per-question SSE event to the dashboard.

---

### GET /results

Returns the full evaluation report once judging is complete. Works for both initial and re-eval session ids.

**Request**
```
GET /results?session_id=<string>
```

**Response — judging still running**
```json
{ "status": "processing" }
```

**Response — ready**
```json
{
  "status": "ready",
  "report": {
    "dimensions": {
      "<dimension enum>": {
        "baseline_score": 72,
        "harness_score":  31,
        "delta":          -41,
        "root_cause":     "string | null",
        "fixable":        true
      }
    }
  },
  "patches": [
    {
      "type":     "skill | system_prompt | tool_definition",
      "filename": "string",
      "content":  "string"
    }
  ]
}
```

On `processing`: back off and retry (start at 3s, cap at 15s, exponential).

---

### POST /reeval

Triggers re-evaluation of specific dimensions after patches have been applied.

**Request**
```json
{
  "session_id":      "string",
  "dimensions":      ["instruction_adherence", "tool_accuracy"],
  "updated_bundle":  {
    "system_prompt": "string | null",
    "skills":        [ { "name": "string", "content": "string" } ],
    "tools":         [ { "name": "string", "definition": {} } ]
  }
}
```

**Response 200**
```json
{ "reeval_session_id": "string" }
```

After receiving `reeval_session_id`, run the same `/next-question` → `/submit-answer` loop under this new session id. The server serves only questions for the specified dimensions. Poll `GET /results?session_id=<reeval_session_id>` for the diff report.

---

### POST /rooms/create

Creates a Pi evaluation room. Returns a one-time join token for Pi and a reusable dashboard key for the browser.

**Request** — no body required

**Response 200**
```json
{
  "room_id":        "string",
  "join_token":     "string",
  "dashboard_key":  "string",
  "dashboard_url":  "string",
  "connection_block": "string (formatted instructions for Pi to paste)"
}
```

---

### GET /rooms/{room_id}/stream

SSE stream for the dashboard. Authorized by `dashboard_key` query parameter.

```
GET /rooms/{room_id}/stream?key=<dashboard_key>
```

Event types pushed: `question_added`, `answer_submitted`, `question_judged`, `session_complete`.

---

### GET /rooms/{room_id}/state

Snapshot of current room state for page reload. Authorized by `dashboard_key` query parameter.

```
GET /rooms/{room_id}/state?key=<dashboard_key>
```

Returns the current session status, all questions with their scores, and the final report if complete.

---

## Latency Delta

`latency_delta` is **not** an LLM-judged dimension — it has no generated questions. The server computes it from `latency_ms` values submitted with answers across all other dimensions, compared against baseline timing. Submit `latency_ms` on every answer.

---

## Polling semantics summary

| Endpoint | Transient status | Retry start | Retry cap |
|---|---|---|---|
| GET /next-question | `not_ready` | 2s | 10s |
| GET /results | `processing` | 3s | 15s |

Use exponential backoff within these bounds. Log retries so the user sees progress.
