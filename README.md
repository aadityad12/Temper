# TEMPER

> "Model cards test the model — TEMPER tests everything around it, and fixes what it finds."

Environment-level evaluation and auto-remediation for AI deployments. Built for the **AI Engineer World's Fair Hackathon 2026** — Best Usage of Gemini track.

---

## What It Does

TEMPER evaluates the **harness** wrapped around a model — the system prompt, skill files, and tool definitions — not the model itself. It identifies where that environment is helping or hurting performance, generates targeted fixes using Gemini, confirms the fixes work, and honestly flags what it cannot fix.

The key output is the **delta column**: harness score minus bare-model baseline on identical questions. A negative delta on Tool Call Accuracy means your harness is actively degrading a capability the model natively has.

---

## Architecture

```
Local (Claude Code)              Cloud (FastAPI + Gemini)
─────────────────────            ────────────────────────────────────
@eval                            POST /register
  bundle collector          →      Gemini generates test questions
  test loop (DeepSeek)      ←      GET /next-question
  submit answers            →      POST /submit-answer
  render report             ←      Gemini judges all answer pairs
                                   GET /results → report + patches

@patch
  apply patches             →    POST /reeval
  re-eval loop              ←      GET /next-question (patched dims)
  render diff               ←      GET /results → updated scores
```

**Model roles:**
| Role | Model |
|---|---|
| Test-taker (harness run) | DeepSeek — called locally with full bundle |
| Baseline | DeepSeek — called bare by the cloud server |
| Judge + question generator | Gemini 2.5 Flash |
| Patch generator | Gemini 2.5 Flash |

---

## Quick Start

### 1. Install

```bash
make install-local    # local layer (.venv in local/)
make install-cloud    # cloud layer (.venv in cloud/)
```

### 2. Configure

```bash
cp .env.example .env
# Fill in:
#   DEEPSEEK_API_KEY=sk-...
#   GEMINI_API_KEY=...
#   ANTIGRAVITY_BASE_URL=http://localhost:8001
```

### 3. Run (offline — no API keys required)

```bash
# Terminal 1
make run-mock            # mock server on port 8000

# Terminal 2
make test-local          # full @eval → @patch against mock
make demo                # render pre-cached reports (no server needed)
```

### 4. Run (live — requires API keys)

```bash
# Terminal 1
make run-cloud           # real cloud server on port 8001

# Terminal 2
make test-cloud          # full @eval → @patch with live Gemini + DeepSeek
```

---

## Commands

| Command | What it does |
|---|---|
| `make run-mock` | Start scripted mock server on port 8000 |
| `make run-cloud` | Start live cloud server on port 8001 (requires API keys) |
| `make run-cloud-offline` | Start cloud server in offline/scripted mode on port 8001 |
| `make test-local` | Full @eval → @patch against mock server (no API keys) |
| `make test-cloud` | Full @eval → @patch against live cloud server |
| `make test-integration` | Integration test asserting villain-env bands (offline, deterministic) |
| `make test-slopcode` | Smoke test for the six-checkpoint SlopLedger demo bench |
| `make demo` | Render pre-cached eval + diff reports (no server needed) |
| `make validate-schemas` | Validate fixtures against JSON schemas |

---

## The Demo Path (3 minutes)

Pre-cached reports render instantly. Live re-eval is the only live computation.

```bash
# No server needed — reads from local/demo_cache/
make demo
```

Or the full live flow:
```bash
# Terminal 1: make run-cloud
# Terminal 2:
cd local
TEMPER_OFFLINE=false ANTIGRAVITY_BASE_URL=http://localhost:8001 python eval.py
TEMPER_OFFLINE=false ANTIGRAVITY_BASE_URL=http://localhost:8001 python patch.py
```

**Demo numbers (villain environment):**

| Dimension | Baseline | Harness | Δ | Status |
|---|---|---|---|---|
| instruction_adherence | 71 | 44 | −27 | NEEDS_PATCH |
| tool_accuracy | 72 | 31 | −41 | NEEDS_PATCH |
| output_format | 88 | 85 | −3 | PASSING |
| skill_trigger | 60 | 52 | −8 | NEEDS_PATCH |
| latency_delta | 90 | 74 | −16 | NEEDS_PATCH |
| error_recovery | 38 | 35 | −3 | STRUCTURAL_LIMITATION |

Post-patch: tool_accuracy 31→79 RESOLVED, instruction_adherence 44→82 RESOLVED.

---

## Cut Order (if something breaks before demo)

Pre-committed. Don't debate at the venue.

1. **Gemini question generation fails** → cloud server falls back to scripted question bank automatically (no action needed)
2. **Cloud server unreachable** → `make test-local` (mock server, same reports, same narrative)
3. **Everything down** → `make demo` (pre-cached reports, zero dependencies)

The rendered report with real scores, real patch artifacts, and the structural-limitation flag are never cut.

---

## Repo Layout

```
local/
  eval.py              @eval entry point
  patch.py             @patch entry point
  bundle.py            env dir → validated bundle
  harness.py           DeepSeek inference (measures latency_ms)
  client.py            HTTP client for all 5 endpoints
  renderer.py          rich terminal report renderer
  demo.py              pre-cached demo player
  demo_cache/          pre-serialised eval + reeval reports
  test_integration.py  integration test (villain env bands)

cloud/
  main.py          FastAPI app — all 5 endpoints
  session.py       session store + state machine
  generator.py     Gemini question generation
  baseline.py      bare DeepSeek baseline runner
  judge.py         Gemini-as-judge scoring
  patcher.py       Gemini patch artifact generation
  config.py        shared env vars

fixtures/
  villain_env/     demo environment (Acme SaaS support)
  sample_eval_report.json
  sample_bundle.json

schemas/
  environment_bundle.schema.json
  eval_report.schema.json

contract/api.md    frozen 5-endpoint API contract
EVAL_GUIDE.md      @eval and @patch orchestration spec
```

---

## Sponsor Integration

| Sponsor | Role |
|---|---|
| **Google / Gemini 2.5 Flash** | Generates test questions, judges answer pairs, produces patch artifacts — load-bearing, not decorative |
| **DigitalOcean** | Hosts the cloud server (FastAPI + uvicorn) |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DEEPSEEK_API_KEY` | live mode | DeepSeek inference key |
| `GEMINI_API_KEY` | live mode | Gemini API key (GCP) |
| `ANTIGRAVITY_BASE_URL` | always | Cloud server URL (default: http://localhost:8001) |
| `TEMPER_OFFLINE` | — | `true` → route local client to mock server |
| `CLOUD_OFFLINE` | — | `true` → cloud server uses scripted responses |
| `DEEPSEEK_MODEL` | — | Default: `deepseek-chat` |
| `GEMINI_MODEL` | — | Default: `gemini-2.5-flash` |
