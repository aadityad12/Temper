# TEMPER — Product Spec
### Environment-level evaluation and remediation for AI deployments

---

## One-liner

> "Model cards test the model — TEMPER tests everything around it, and fixes what it finds."

---

## What TEMPER Is

TEMPER is an environment-level evaluation and auto-remediation system for AI deployments. It tests not the raw model — that is what model cards already do — but the entire package wrapped around it: the system prompt, skill files, tool definitions, and harness configuration. It identifies where that environment is helping or hurting model performance, generates targeted fixes, re-evaluates to confirm improvement, and honestly flags what it cannot fix.

**The core insight:** the same model performs dramatically differently across different environments. No existing tool measures this. TEMPER does — and it proves it with a number: the delta between your harness run and a bare model baseline on identical questions.

---

## What TEMPER Is Not

- Not a replacement for model cards or standard benchmarks. Those test the model. TEMPER tests the environment.
- Not a prompt optimizer. It diagnoses specific failure modes and writes targeted artifacts to address them.
- Not a model training tool. It does not touch weights.
- Not a monitoring tool. It is a diagnostic and remediation system run on demand.
- Not passive. It acts on what it finds.

---

## Model Roles

| Role | Model |
|---|---|
| **Test-taker — local path** | DeepSeek API, called through the user's local harness by `local/harness.py` |
| **Test-taker — Pi path** | The Pi coding agent itself, answering with its own capabilities |
| **Baseline** | DeepSeek API, called bare with no harness by the cloud server |
| **Judge + question generator** | Gemini 2.5 Flash |
| **Patch generator** | Gemini 2.5 Flash |

**Why this model split:**
- Using the same model (DeepSeek) for both the baseline and harness run eliminates model capability as a variable. The only difference between the two runs is the harness. The delta is clean.
- Gemini judging both runs is structurally unbiased — it has no stake in either outcome.

---

## Architecture

### Communication Model

The TEMPER cloud server is the server. Clients (local scripts or Pi agent) make outbound HTTP calls — no WebSockets, no NAT issues for the core protocol. The dashboard uses SSE for live updates.

```
Client                       TEMPER Cloud Server (FastAPI)
──────                       ────────────────────────────
POST /register           →   create session, start generation + baseline
GET  /next-question      ←   serve questions one at a time
POST /submit-answer      →   store answer + latency
GET  /results            ←   report + patches (once judging complete)
POST /reeval             →   re-judge patched dimensions only
```

For the Pi live dashboard path:

```
Dashboard (browser)          TEMPER Cloud Server
────────────────────         ────────────────────────────
POST /rooms/create       →   issue room_id + tokens
GET  /rooms/{id}/stream  ←   SSE: live question/score events
GET  /rooms/{id}/state   ←   snapshot for page reload
```

### Full Pipeline

```
[Client — local scripts or Pi agent]
│
│  Client calls: @eval / temper_register
│
▼
[Bundle Collection]
   Packages the environment under test:
     - system_prompt.md
     - skills/*.md
     - tools/*.json
   Validates against environment_bundle.schema.json
   Ships to cloud server via POST /register
│
                    ┌─────────────────────────────────────┐
                    │  TEMPER Cloud Server (FastAPI)       │
                    │  Deployed on DigitalOcean            │
                    │                                      │
                    │  1. Gemini reads the bundle          │
                    │     Understands the harness domain,  │
                    │     constraints, tools, skills       │
                    │                                      │
                    │  2. Generates test questions         │
                    │     Per dimension, calibrated to     │
                    │     this specific environment        │
                    │                                      │
                    │  3. Runs bare DeepSeek baseline      │
                    │     Same questions, no harness       │
                    │     Records baseline answers         │
                    │                                      │
                    │  4. Queues questions for client      │
                    └─────────────────────────────────────┘
│
▼
[Test Loop — client polls cloud server]

  LOOP:
    Client: GET /next-question
    Server: returns next test question (or done)

    Client: runs question through its capabilities
            (local: DeepSeek with full bundle context)
            (Pi: agent's own model + skills + tools)

    Client: POST /submit-answer {question_id, answer, latency_ms}

    Repeat until server returns done
│
▼
[Judgment — cloud server]

  Gemini receives:
    - All baseline answers (bare DeepSeek)
    - All client answers (through the harness)
    - The environment bundle (context for scoring)

  Gemini scores each answer pair per dimension: 0–100
  Computes delta: harness score minus baseline score
  Identifies root cause per failing dimension
  Generates targeted patch artifacts
│
▼
[Client polls GET /results]
   Receives report + patch artifacts
   Renders report
   Holds patches for the re-eval step
│
│  User triggers re-evaluation (@patch or /patch in Pi)
▼
[Patch Application]
   Patches applied to the bundle:
     - Instruction Adherence gap    → system prompt patch
     - Tool Call Accuracy gap       → corrected tool definition + skill
     - Output Format gap            → skill with format templates
     - Skill Trigger Precision gap  → skill activation condition rewrite
     - Latency Delta gap            → skill trimming context
     - Error Recovery gap           → skill with recovery paths
│
▼
[Re-eval Loop]
   Client re-runs the test loop on patched dimensions ONLY
   Server re-judges those dimensions with updated harness

   Score improved: → RESOLVED
   Score did not improve: → STRUCTURAL LIMITATION
     "This is a model ceiling. No harness skill can fix this."
```

---

## The Six Eval Dimensions

### 1. Instruction Adherence
**Tests:** Does the model follow the constraints, rules, and behavioral specs in the system prompt and skill files?
**How:** Gemini extracts the specific constraints from the bundle, generates adversarial probes of those exact rules.
**Fixes:** System prompt patch clarifying ambiguities, resolving contradictions, strengthening weak specifications.

### 2. Tool / Function Call Accuracy
**Tests:** Are defined tools being called with correct parameters at correct times? Are there hallucinated parameters, wrong tool selections, missed invocations?
**How:** Gemini generates tasks requiring the specific tools in the bundle, evaluates call correctness against defined schemas.
**Fixes:** Corrected tool definition + skill with explicit usage patterns and call examples.

### 3. Output Format Compliance
**Tests:** Is the model producing outputs in the structure the harness requires — JSON schema, markdown format, field names, response templates?
**How:** Gemini generates tasks that should trigger structured output, evaluates against format specs in the bundle.
**Fixes:** Skill with explicit format templates and positive/negative output examples.

### 4. Skill Trigger Precision
**Tests:** Are defined skills invoked at the right times? Covers both false negatives (missed triggers) and false positives (wrong triggers).
**How:** Gemini generates scenarios that should and should not trigger each skill, evaluates invocation accuracy.
**Fixes:** Rewrites of skill activation conditions — tightening or broadening trigger definitions as needed.

### 5. Latency Delta
**Tests:** Is the harness adding meaningful overhead? Compares response time between baseline (bare DeepSeek, no harness) and harness run.
**How:** Measured directly from `latency_ms` on each submitted answer. No LLM judgment — raw timing data.
**Fixes:** Skill that trims unnecessary context, restructures prompt assembly, or flags runaway token usage.

### 6. Error Recovery Rate
**Tests:** When the model produces a malformed output or hits a failure case, does the harness help it self-correct or compound the error?
**How:** Gemini injects failure cases calibrated to the most likely failure modes in this harness, evaluates whether the environment enables recovery.
**Fixes:** Skill with explicit recovery path definitions and fallback behavior specifications.

---

## The Delta Column

The delta (harness score minus baseline score) is TEMPER's unique output.

| Delta | Meaning |
|---|---|
| **Positive** | Your harness is making the model better on this dimension |
| **Negative** | Your harness is actively making the model worse |
| **Near-zero** | Your harness is neither helping nor hurting here |

Because both runs use the same model (DeepSeek) on identical questions, the delta isolates exactly what the harness contributes. A negative delta on Tool Call Accuracy means your harness is degrading a capability the model natively has.

---

## Remediation Logic

Artifact type is determined by failure mode:

| Dimension | Artifact Generated |
|---|---|
| Instruction Adherence | System prompt patch |
| Tool Call Accuracy | Corrected tool definition + skill with usage patterns |
| Output Format Compliance | Skill with format templates |
| Skill Trigger Precision | Skill activation condition rewrite |
| Latency Delta | Skill with context trimming guidance |
| Error Recovery Rate | Skill with recovery paths + system prompt patch |

---

## The Re-eval Loop

TEMPER does not trust its own patches.

After patches are applied, the client re-runs the test loop on patched dimensions only — not a full suite re-run. The server re-judges those dimensions with the updated harness answers.

- Score improves → dimension marked **RESOLVED**
- Score does not improve → dimension flagged as **STRUCTURAL LIMITATION** with explanation

The honest failure case is a feature. A system that knows what it cannot fix is more trustworthy than one that patches everything silently.

---

## Sponsor Integration

| Sponsor | Integration |
|---|---|
| **Google / Gemini 2.5 Flash** | Judges all eval runs, generates test cases, identifies root causes, generates patch artifacts — architectural, not decorative |
| **DigitalOcean** | Hosts the TEMPER cloud server (FastAPI + uvicorn) |
