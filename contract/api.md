# TEMPER API contract

This reference describes the endpoints implemented by `cloud/main.py` on the default branch. The Python client uses the five evaluation endpoints. Pi room mode also uses room creation, state, and server-sent events.

## Common behavior

- The local default base URL is `http://localhost:8001` when using `.env.example`.
- Unknown sessions return HTTP 404 with a FastAPI `detail` field.
- Evaluation sessions are stored in memory and disappear when the process restarts.
- The server does not currently validate a legacy bundle against `schemas/environment_bundle.schema.json`.
- The `report` returned by `/results` is a compact projection and does not satisfy the full report schema by itself.

The evaluation dimension keys are:

```text
instruction_adherence
tool_accuracy
output_format
skill_trigger
latency_delta
error_recovery
```

Pi coding-bench rooms return `coding_bench` instead of those six dimensions.

## Evaluation endpoints

### `POST /register`

Creates an initial evaluation session. Legacy local-client registration requires `bundle`. Pi registration additionally requires a room ID and one-time token.

Local request:

```json
{
  "bundle": {
    "system_prompt": "string or null",
    "skills": [{"name": "skill_name", "content": "full Markdown"}],
    "tools": [{"name": "tool_name", "definition": {}}]
  }
}
```

Pi request:

```json
{
  "room_id": "room identifier",
  "token": "one-time join token",
  "bundle": {
    "system_prompt": "string or null",
    "skills": [],
    "tools": []
  },
  "bench": false
}
```

Success:

```json
{"session_id": "sess_12345678"}
```

Implemented errors include:

| Status | Condition |
|---:|---|
| 400 | Neither a bundle nor room credentials were provided, or a Pi bundle has no prompt, skills, or tools. |
| 403 | Room ID and join token do not match. |
| 409 | Join token was already used or the room already has a session. |
| 422 | The legacy bundle is not an object or contains none of `system_prompt`, `skills`, or `tools`; or FastAPI could not validate the outer request body. The body uses `detail`, not `error`. |

The local path starts question generation and the batch bare-model baseline in an asynchronous task. The Pi path starts question generation first and runs a bare-model answer after each Pi submission.

### `GET /next-question`

```http
GET /next-question?session_id=sess_12345678
```

Possible successful bodies:

```json
{"status": "not_ready"}
```

```json
{
  "status": "question",
  "question_id": "q_ia_1",
  "dimension": "instruction_adherence",
  "prompt": "Question text"
}
```

```json
{"status": "done"}
```

The endpoint advances an in-memory cursor when it serves a question. It does not wait for the prior question's answer before serving the next one.

The local client retries `not_ready` with exponential backoff starting at 2 seconds and capped at 10 seconds.

### `POST /submit-answer`

```json
{
  "session_id": "sess_12345678",
  "question_id": "q_ia_1",
  "answer": "serialized answer text",
  "latency_ms": 312,
  "input_tokens": 42,
  "output_tokens": 87
}
```

`input_tokens` and `output_tokens` are optional. The dashboard shows them when the Pi client supplies them. `latency_ms` is required by the request model.

Success:

```json
{"received": true}
```

Unknown sessions or question IDs return HTTP 404. Submitting the same question ID again replaces its stored answer. On the default branch, repeated Pi submissions can also start repeated background judge tasks.

### `GET /results`

```http
GET /results?session_id=sess_12345678
```

While generation, answer collection, or judging is incomplete:

```json
{"status": "processing"}
```

When ready:

```json
{
  "status": "ready",
  "report": {
    "dimensions": {
      "tool_accuracy": {
        "baseline_score": 72,
        "harness_score": 31,
        "delta": -41,
        "status": "NEEDS_PATCH",
        "root_cause": "string or null",
        "fixable": true,
        "structural_reason": null,
        "fix_type": "tool_definition",
        "test_cases_run": 2,
        "latency_baseline_ms": null,
        "latency_harness_ms": null
      }
    }
  },
  "patches": [
    {
      "type": "tool_definition",
      "filename": "tools/lookup_order.json",
      "content": "complete replacement file"
    }
  ]
}
```

The local client retries `processing` with exponential backoff starting at 3 seconds and capped at 15 seconds.

### `POST /reeval`

Creates a new session linked to an existing session ID. The server does not verify that dimension names are members of the documented enum.

```json
{
  "session_id": "sess_12345678",
  "dimensions": ["instruction_adherence", "tool_accuracy"],
  "updated_bundle": {
    "system_prompt": "replacement prompt",
    "skills": [],
    "tools": []
  }
}
```

Success:

```json
{"reeval_session_id": "reeval_12345678"}
```

The client repeats the `/next-question`, `/submit-answer`, and `/results` loop with the new session ID. Question generation is limited to the requested dimensions.

## Pi room endpoints

### `POST /rooms/create`

The optional `bench=true` query parameter puts the eventual Pi session into coding-bench mode.

```http
POST /rooms/create?bench=false
```

Success:

```json
{
  "room_id": "12-character identifier",
  "join_token": "one-time token",
  "dashboard_key": "reusable browser key",
  "token": "backward-compatible alias of join_token",
  "dashboard_url": "http://localhost:8001/room/ROOM?key=KEY",
  "connection_block": "instructions for the Pi agent"
}
```

The process stores both credentials in memory. The dashboard key appears in the URL query string.

### `GET /rooms/{room_id}/state`

```http
GET /rooms/ROOM/state?key=DASHBOARD_KEY
```

Returns a snapshot containing:

```json
{
  "room_id": "ROOM",
  "pi_connected": false,
  "status": "waiting",
  "questions": [],
  "report": null,
  "patches": [],
  "baseline_model": "deepseek-chat",
  "judge_model": "gemini-3.5-flash"
}
```

An unknown room or incorrect key returns HTTP 403. The response does not distinguish those cases.

### `GET /rooms/{room_id}/stream`

```http
GET /rooms/ROOM/stream?key=DASHBOARD_KEY
```

The endpoint returns `text/event-stream`, sends a comment ping every 30 seconds while idle, and emits JSON in `data:` frames.

Implemented event types are:

| Event | Main fields |
|---|---|
| `connected` | `room_id` |
| `pi_connected` | none |
| `questions_ready` | `questions` |
| `pi_submitted` | question ID, dimension, latency, token counts |
| `question_judged` | scores, delta, verdict, latency, token counts |
| `session_complete` | report and patches |

## Current latency behavior

The request contract requires harness `latency_ms`. Scoring behaves as follows:

- Pi per-question mode computes latency scores from the baseline and Pi timing on `latency_delta` questions.
- Batch mode averages the baseline and harness timing fields for `latency_delta` questions.
- Both paths map time to `max(0, 100 - floor(milliseconds / 20))` and compute harness minus baseline.
- When either side has no usable timing data, the service returns the scripted fallback timing and score values.

This score is a coarse project-specific transformation, not a controlled performance benchmark. It does not isolate network, provider, or model variance.
