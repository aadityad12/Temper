# TEMPER
### Environment-level evaluation and remediation for AI deployments

---

## One-liner

> "Model cards test the model — TEMPER tests everything around it, and fixes what it finds."

---

## Hackathon Context

| Field | Value |
|---|---|
| Event | AI Engineer World's Fair Hackathon 2026 |
| Primary Track | **The Self-Improvement Stack** |
| Secondary Flavor | Continual Learning (closed remediation loop) |
| Prize Target | **Best Usage of Gemini 3.5** ($25 GCP credits, all inference funded) |
| Infrastructure | DigitalOcean (Antigravity hosting) |
| Team Size | 2 |

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

| Role | Model | Cost |
|---|---|---|
| **Test-taker (harness run)** | DeepSeek API, called through the user's local harness | DeepSeek free tier / minimal cost |
| **Baseline** | DeepSeek API, called bare with no harness by Antigravity | Same |
| **Judge** | Gemini (via GCP) | Covered by $25 hackathon GCP credits |

**Why this model split:**
- Using the same model (DeepSeek) for both the baseline and harness run eliminates model capability as a variable. The only difference between the two runs is the harness. The delta is clean.
- Gemini judging both runs is structurally unbiased — it has no stake in either outcome.
- Zero Claude API spend. Claude Code is the execution environment on the local machine, not the inference model.

---

## Architecture

### The Communication Model

Antigravity is the server. Claude Code is the client. All communication is outbound HTTP from Claude Code to Antigravity — no NAT issues, no real-time infrastructure required.

```
Antigravity (cloud) exposes HTTP endpoints:
  GET  /next-question     → returns next queued test question
  POST /submit-answer     → receives Claude Code's harness answer
  GET  /results           → returns full eval report + patch artifacts

Claude Code (local) drives the loop:
  POLL /next-question → run through harness → POST /submit-answer
  Repeat until queue empty
  POLL /results → render report → apply patches on @patch
```

### Full Pipeline

```
[Claude Code — User's Local Machine]
│
│  User runs: @eval
│
▼
[EVAL_GUIDE.md]
   Claude Code reads this at session start.
   Tells the agent:
     - Collect the environment bundle
     - Register with Antigravity and start the test loop
     - Render the returning report
     - Expose the @patch command
│
▼
[Bundle Collector — Claude Code]
   Scrapes and packages the user's environment:
     - system_prompt.md
     - skills/*.md
     - Tool definitions (JSON/YAML)
   Outputs: environment_bundle.json
   Ships to Antigravity via POST /register
│
                    ┌─────────────────────────────────────┐
                    │  ANTIGRAVITY — Google Cloud          │
                    │  Hosted on DigitalOcean              │
                    │                                      │
                    │  On receiving environment_bundle:    │
                    │                                      │
                    │  1. Gemini reads the bundle          │
                    │     Understands the harness:         │
                    │     its domain, constraints,         │
                    │     tools, skill definitions         │
                    │                                      │
                    │  2. Generates test questions         │
                    │     Per dimension, calibrated        │
                    │     to THIS specific environment     │
                    │     As many as needed for            │
                    │     confident signal — not           │
                    │     a fixed quota                    │
                    │                                      │
                    │  3. Runs bare DeepSeek baseline      │
                    │     Same questions, no harness       │
                    │     Records baseline answers         │
                    │                                      │
                    │  4. Queues questions for             │
                    │     Claude Code to answer            │
                    └─────────────────────────────────────┘
│
▼
[Test Loop — Claude Code polls Antigravity]

  LOOP:
    Claude Code: GET /next-question
    Antigravity: returns next test question (or DONE)
    
    Claude Code: runs question through user's full harness
                 (system prompt + skills + tools + DeepSeek inference)
    
    Claude Code: POST /submit-answer  {question_id, answer, latency_ms}
    
    Repeat until Antigravity returns DONE
│
▼
[Judgment — Antigravity]

  Gemini receives:
    - All baseline answers (bare DeepSeek)
    - All harness answers (Claude Code + DeepSeek)
    - The environment bundle (to know what the harness was supposed to do)

  Gemini scores each answer pair per dimension: 0–100
  Computes delta: harness score minus baseline score
  Identifies root cause per failing dimension
  Generates targeted patch artifacts

  Packages: eval_report.json + patch_artifacts/
│
▼
[Claude Code polls GET /results]
   Receives eval_report.json and patch artifacts
   Renders report to user in terminal
   Holds patches ready for @patch command
│
│  User reviews report, runs: @patch
▼
[Patch Writer — Claude Code]
   Writes correct artifact type per failure mode:
     - Instruction Adherence gap    → system prompt patch
     - Tool Call Accuracy gap       → corrected tool definition
     - Output Format gap            → SKILL.md with format templates
     - Skill Trigger Precision gap  → rewrites skill activation conditions
     - Latency Delta gap            → SKILL.md trimming context / restructuring
     - Error Recovery gap           → SKILL.md with recovery path definitions
   Writes artifacts directly into user's project
│
▼
[Re-eval Loop]
   Claude Code re-runs the test loop on patched dimensions ONLY
   Antigravity re-judges those dimensions with updated harness
   
   Score improved above threshold (+20pts default): → RESOLVED
   Score did not improve: → STRUCTURAL LIMITATION
     "This is a model ceiling. No skill can fix this."
     Surfaces explanation of why and what would actually fix it
```

---

## The Six Eval Dimensions

Test case count per dimension is determined by **confident signal**, not quota. Gemini generates cases until it has reliable signal, then stops.

### 1. Instruction Adherence
**Tests:** Does the model follow the constraints, rules, and behavioral specs in the system prompt and skill files?
**How:** Gemini extracts the specific constraints from the bundle, generates adversarial probes of those exact rules — not generic instruction following.
**Fixes:** System prompt patch clarifying ambiguities, resolving contradictions, strengthening weak specifications.

### 2. Tool / Function Call Accuracy
**Tests:** Are defined tools being called with correct parameters at correct times? Are there hallucinated parameters, wrong tool selections, missed invocations?
**How:** Gemini generates tasks requiring the specific tools in the user's bundle, evaluates call correctness against defined schemas.
**Fixes:** Corrected tool definition + SKILL.md with explicit usage patterns and call examples.

### 3. Output Format Compliance
**Tests:** Is the model producing outputs in the structure the harness requires — JSON schema, markdown format, field names, response templates?
**How:** Gemini generates tasks that should trigger structured output, evaluates against format specs in the bundle.
**Fixes:** SKILL.md with explicit format templates and positive/negative output examples.

### 4. Skill Trigger Precision
**Tests:** Are defined skills invoked at the right times? Covers both false negatives (missed triggers) and false positives (wrong triggers).
**How:** Gemini generates scenarios that should and should not trigger each skill, evaluates invocation accuracy.
**Fixes:** Rewrites of skill activation conditions — tightening or broadening trigger definitions as needed.
**Note:** Unique to environment-level testing. No standard benchmark measures this.

### 5. Latency Delta
**Tests:** Is the harness adding meaningful overhead? Compares response time between baseline (bare DeepSeek, no harness) and harness run.
**How:** Measured directly from latency_ms field in each submitted answer. No LLM judgment needed — raw timing data.
**Fixes:** SKILL.md that trims unnecessary context, restructures prompt assembly, or flags runaway token usage.

### 6. Error Recovery Rate
**Tests:** When the model produces a malformed output or hits a failure case, does the harness help it self-correct or compound the error?
**How:** Gemini injects failure cases calibrated to the most likely failure modes in this specific harness, evaluates whether the environment enables recovery.
**Fixes:** SKILL.md with explicit recovery path definitions and fallback behavior specifications.

---

## The Delta Column

The delta (harness score minus baseline score) is TEMPER's unique output.

| Delta | Meaning |
|---|---|
| **Positive** | Your harness is making the model better on this dimension |
| **Negative** | Your harness is actively making the model worse |
| **Near-zero** | Your harness is neither helping nor hurting here |

Because both runs use the same model (DeepSeek) on identical questions, the delta isolates exactly what the harness contributes. No model variable noise. Clean signal.

A negative delta on Tool Call Accuracy means your harness is degrading a capability the model natively has. This is the number that makes people immediately understand why TEMPER exists.

---

## Remediation Logic

Artifact type is determined by failure mode:

| Dimension | Artifact Generated |
|---|---|
| Instruction Adherence | System prompt patch |
| Tool Call Accuracy | Corrected tool definition + SKILL.md with usage patterns |
| Output Format Compliance | SKILL.md with format templates |
| Skill Trigger Precision | Skill activation condition rewrite |
| Latency Delta | SKILL.md with context trimming guidance |
| Error Recovery Rate | SKILL.md with recovery paths + system prompt patch |

---

## The Re-eval Loop

TEMPER does not trust its own patches.

After @patch writes artifacts, Claude Code re-runs the test loop on patched dimensions only — not a full suite re-run. Antigravity re-judges those dimensions with the updated harness answers.

- Score improves above threshold → dimension marked **RESOLVED**
- Score does not improve → dimension flagged as **STRUCTURAL LIMITATION** with explanation

The honest failure case is a feature. A system that knows what it cannot fix is more trustworthy than one that patches everything silently. This moment matters in the demo.

---

## Build Split

### Person 1 — Local Layer (Claude Code)
**Owns:**
- EVAL_GUIDE.md
- Bundle collector (scrapes system prompt, SKILL.md files, tool definitions into environment_bundle.json)
- Test loop (polls /next-question, runs through harness, posts to /submit-answer)
- Report renderer (reads eval_report.json, presents scores + delta + diagnosis in terminal)
- @patch command (writes correct artifact type per gap into user's project)
- Re-eval trigger (re-runs loop on patched dimensions only)

**Can start:** Immediately. No blockers. The HTTP endpoints can be mocked locally until Person 2 has Antigravity running.

**Definition of done:** @eval runs the full test loop against a live Antigravity instance. @patch writes real artifacts. Re-eval triggers and updates the report.

### Person 2 — Cloud Layer (Antigravity + Gemini)
**Owns:**
- Antigravity setup and HTTP endpoint exposure (hosted on DigitalOcean)
- POST /register (receives bundle, triggers test generation)
- Gemini reads bundle, generates calibrated test questions per dimension
- Bare DeepSeek baseline run (same questions, no harness)
- GET /next-question and POST /submit-answer queue management
- Gemini judgment (scores all answer pairs, computes delta, identifies root causes)
- Patch artifact generation (correct artifact type per failure mode)
- GET /results (returns eval_report.json + patch_artifacts/)
- Re-eval endpoint (re-judges patched dimensions on demand)

**Can start:** Antigravity spike is first task, Day 1, first 2 hours.

**Hard spike deadline:** If Antigravity is not returning responses by hour 2, pivot to a simple Flask/FastAPI server on DigitalOcean running the same logic. Same endpoints, same Gemini calls, no Antigravity-specific APIs. Do not debate this — switch immediately.

**Definition of done:** A valid eval_report.json with real scores across all 6 dimensions, delta column populated, root cause flags, and patch artifacts for at least 2 failing dimensions.

---

## API Contract Between Person 1 and Person 2

This is the first 30 minutes of hacking. Both people agree on this schema before writing a single line of code.

```json
POST /register
Body: {
  "bundle": {
    "system_prompt": "string",
    "skills": [{"name": "string", "content": "string"}],
    "tools": [{"name": "string", "definition": "object"}]
  }
}
Response: { "session_id": "string" }

GET /next-question?session_id=xxx
Response: {
  "status": "question" | "done",
  "question_id": "string",
  "dimension": "instruction_adherence" | "tool_accuracy" | ...,
  "prompt": "string"
}

POST /submit-answer
Body: {
  "session_id": "string",
  "question_id": "string",
  "answer": "string",
  "latency_ms": number
}
Response: { "received": true }

GET /results?session_id=xxx
Response: {
  "status": "ready" | "processing",
  "report": {
    "dimensions": {
      "instruction_adherence": {
        "baseline_score": number,
        "harness_score": number,
        "delta": number,
        "root_cause": "string",
        "fixable": boolean
      },
      ...
    }
  },
  "patches": [
    {
      "type": "skill" | "system_prompt" | "tool_definition",
      "filename": "string",
      "content": "string"
    }
  ]
}

POST /reeval
Body: {
  "session_id": "string",
  "dimensions": ["instruction_adherence", ...],
  "updated_bundle": { ... }
}
Response: { "reeval_session_id": "string" }
```

---

## Demo Path (3 Minutes)

**Pre-demo setup (non-negotiable):**
Build the villain environment before hacking starts — a real project with:
- A system prompt with two contradictory instructions
- A tool definition missing parameter constraints
- A skill with ambiguous trigger conditions causing missed activations

Pre-run the full eval. Cache eval_report.json with real scores. The only live computation in the demo is the re-eval on two dimensions. Everything else loads from cache.

Know your numbers cold before walking up.

---

**0:00 – 0:20 | The problem**
Show the villain environment in Claude Code — system prompt, skill files, tool definitions visible on screen. One line: *"This is a production AI environment. The model card says the model is performing well. TEMPER disagrees."* Run @eval.

**0:20 – 0:50 | The report loads**
Pre-cached report renders. Six dimensions. Scores. The delta column. Pause on two numbers: *"Tool Call Accuracy: 31. Instruction Adherence: 44. This harness is actively making the model worse on both."* Three seconds of silence. Do not explain the architecture.

**0:50 – 1:20 | One gap in detail**
Drill into Tool Call Accuracy. Show the specific test cases Gemini ran, the failure pattern, the root cause diagnosis. Deliver: *"The tool definition doesn't constrain parameters. The model produces valid-looking but incorrect calls 70% of the time. Gemini caught this. The model couldn't catch it evaluating itself."*

**1:20 – 1:40 | The patch**
Run @patch. Watch two artifacts appear in the project tree in real time — a corrected tool definition and a new SKILL.md. Say nothing while this happens.

**1:40 – 2:20 | Live re-eval**
Re-eval fires on Tool Call Accuracy and Instruction Adherence only. While it runs: *"TEMPER doesn't trust its own patches. It re-evaluates every dimension it touched. If the score doesn't move, it tells you it's a model ceiling — not a fixable environment problem."* Scores return: 31 → 79. 44 → 82.

**2:20 – 2:45 | The honest failure case**
Show one dimension that did not improve — Error Recovery Rate stayed flat. TEMPER flagged it: *"Structural limitation. No skill can fix this."* This is the moment that separates TEMPER from every other "AI generates suggestions" project at this hackathon.

**2:45 – 3:00 | Close**
*"Model cards test the model. TEMPER tests everything around it — and fixes what it can."*

---

## The Load-Bearing Component

**The pre-cached eval_report.json rendering correctly with the right numbers.**

Every sentence in the demo references something on that report. If it fails to render, the demo dies at second 20 with no pivot.

**Mitigation:** The renderer reads local JSON, not a live API call. Pre-generate the report before the demo slot. Validate every number. Commit it to the repo. The renderer must work offline. Non-negotiable.

---

## Cut Order (If Time Pressure Hits)

Pre-committed. Do not make this decision at 3am.

1. **First cut — Dynamic test case generation.** Gemini selects from a strong pre-written test bank per dimension rather than generating from scratch. Demo is indistinguishable to a judge.
2. **Second cut — Antigravity.** Replace with a simple Flask/FastAPI server on DigitalOcean. Same endpoints, same Gemini calls. Every score and the delta survive intact.
3. **Third cut — Live re-eval.** Pre-cache post-patch scores alongside the pre-patch report. Narrative holds. You lose the live computation moment only.

**Never cut:** The rendered report with real scores. The patch writer producing real artifacts. The honest failure case flagging structural limitations. These three are the product.

---

## Sponsor Integration

| Sponsor | Integration | Legitimacy |
|---|---|---|
| **Google / Gemini 3.5** | Gemini judges all eval runs, generates test cases, identifies root causes, generates patch artifacts | Architectural — Gemini is load-bearing, not decorative |
| **DigitalOcean** | Hosts the Antigravity server (or Flask fallback) | Clean infrastructure fit |

---

## Out of Scope (Hackathon Build)

- Multi-model support beyond DeepSeek (architecture is model-agnostic, implementation is not)
- Web UI (Claude Code terminal is the interface)
- Eval history or longitudinal tracking across sessions
- Custom eval dimension configuration by the user
- Batch evaluation across multiple environments simultaneously
- Model routing recommendations

All natural V2 features. None needed for the demo or judging criteria.

---

## Project Lineage

TEMPER follows FORGE (live LoRA fine-tuning during demo) and Accordion (LLM context management with FOLD_RANK). The name continues the metallurgy thread: FORGE burns material in, TEMPER strengthens through controlled cycles. The re-eval loop is the cycle.
