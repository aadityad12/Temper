# TEMPER local workflow

This guide describes the implemented Python evaluation and patch flow in `local/eval.py` and `local/patch.py`. See [`contract/api.md`](contract/api.md) for request and response shapes. The Pi-specific protocol is in [`extension/skills/temper_protocol.md`](extension/skills/temper_protocol.md).

## Modes

| Mode | Server | Model calls | Purpose |
|---|---|---|---|
| Cached demo | none | none | Render committed example reports with `make demo`. |
| Mock client flow | `local/mock_server.py` on port 8000 | none | Exercise the local polling and renderer path with `make test-local`. |
| Cloud offline | `cloud/main.py` with `CLOUD_OFFLINE=true` | none | Exercise the real FastAPI pipeline with scripted questions, scores, and patches. |
| Live | `cloud/main.py` | DeepSeek and Gemini | Run the external model integrations. This path is not deterministic. |

Offline outputs are fixtures. They do not measure a live model or demonstrate general patch effectiveness.

## Setup

```bash
python3 -m venv local/.venv
local/.venv/bin/python -m pip install -r local/requirements.txt

python3 -m venv cloud/.venv
cloud/.venv/bin/python -m pip install -r cloud/requirements.txt
```

For live mode, copy `.env.example` to `.env`, set both API keys, and set `DEEPSEEK_MODEL` explicitly. Both the local harness and cloud baseline read the same root file.

## Evaluation flow

Run from the repository root:

```bash
TEMPER_OFFLINE=false \
ANTIGRAVITY_BASE_URL=http://localhost:8001 \
local/.venv/bin/python local/eval.py fixtures/villain_env
```

If no environment directory is supplied, `local/eval.py` uses `fixtures/villain_env`.

The command performs these steps:

1. `local/bundle.py` reads `system_prompt.md`, `skills/*.md`, and `tools/*.json` from the target directory.
2. It adds a UUID, timestamp, and content hash, then validates the bundle against `schemas/environment_bundle.schema.json`.
3. The API-shaped prompt, skill, and tool fields are sent to `POST /register`.
4. The client polls `GET /next-question`. `not_ready` responses use exponential backoff from 2 to 10 seconds.
5. For each question, `local/harness.py` sends the prompt to DeepSeek with the full bundle as system context. Tool calls are serialized into the submitted answer string.
6. The client sends the answer and measured inference time to `POST /submit-answer`.
7. The client polls `GET /results`. `processing` responses use exponential backoff from 3 to 15 seconds.
8. The terminal renderer prints the report and saves local runtime artifacts.

The evaluation writes:

```text
local/last_session_id.txt
local/last_report.json
local/last_patches.json
local/patches/               flattened review copies of returned patch files
```

These runtime files are ignored by Git.

## Patch and re-evaluation flow

Run this only after reviewing the returned patch content:

```bash
TEMPER_OFFLINE=false \
ANTIGRAVITY_BASE_URL=http://localhost:8001 \
local/.venv/bin/python local/patch.py fixtures/villain_env
```

`local/patch.py` performs these steps:

1. Reads the prior session and report from `local/last_session_id.txt` and `local/last_report.json`.
2. Reads the original patch objects from `local/last_patches.json`.
3. Selects dimensions whose rendered status is `NEEDS_PATCH`.
4. Writes each full replacement file to `env_dir / patch.filename`.
5. Re-collects and validates the updated bundle.
6. Calls `POST /reeval` with the selected dimensions.
7. Runs the same question and answer loop for the returned re-evaluation session.
8. Saves `local/last_reeval_report.json` and renders a before and after table.

Writing patches is destructive at the file level. It overwrites target files and can create new paths. Run it only in version-controlled data with a clean worktree, and inspect `local/last_patches.json` before applying.

## Deterministic verification

```bash
make demo
make validate-schemas
make test-integration
```

`make test-integration` starts the cloud service on port 8002 with `CLOUD_OFFLINE=true`. The initial phase serves 12 questions, two for each dimension. It applies three canned replacement files and re-evaluates the four dimensions classified as patchable, producing eight more questions. The test asserts initial score directions and the fixed re-evaluation movements for instruction adherence and tool accuracy.

The integration runner checks out `fixtures/villain_env/` before and after execution. Do not run it while that directory contains uncommitted work.

## Environment variables

| Variable | Default | Behavior |
|---|---|---|
| `DEEPSEEK_API_KEY` | empty | Required for live local harness and cloud baseline calls. |
| `DEEPSEEK_MODEL` | module-dependent | Set explicitly to keep the local and bare-baseline model IDs identical. |
| `GEMINI_API_KEY` | empty | Required for live cloud question, judge, and patch calls. |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Cloud model ID. |
| `ANTIGRAVITY_BASE_URL` | `http://localhost:8000` | Local client server URL unless `TEMPER_OFFLINE=true`. |
| `TEMPER_OFFLINE` | `false` | Forces the mock service on port 8000 and a canned local answer when true. |
| `CLOUD_OFFLINE` | `false` | Uses canned cloud questions, answers, scores, and patches when true. |
| `CLOUD_PORT` | `8001` | Cloud bind port. `PORT` is the secondary deployment fallback. |
| `TEMPER_HOST_URL` | local service URL | Base URL placed in Pi connection blocks. |

## Current behavior to account for

- `latency_delta` uses mean recorded inference times when both sides provide timing data, then maps milliseconds to a simple score. Missing timing on either side triggers the scripted fallback.
- `error_recovery` is always classified as structural.
- The live generator can fall back to scripted questions after a Gemini error. The live patcher can fall back to canned Acme fixture patches, which are marked with `is_fallback: true`.
- `local/client.py` retries transport errors, including HTTPX timeouts, and HTTP status errors up to three attempts.
- The service does not persist sessions. A restart invalidates all session and room state.
