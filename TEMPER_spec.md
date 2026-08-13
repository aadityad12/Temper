# TEMPER design and evaluation semantics

This document explains the implemented prototype and the reasoning behind it. It is not a roadmap or a record of production performance.

## Problem framing

An AI system's behavior depends on more than model weights. System instructions, loaded skills, tool schemas, and prompt assembly can improve or degrade the same model. TEMPER packages those inputs as an environment bundle and compares answers produced with and without that bundle.

For the local Python path:

```text
delta = harness-scoped DeepSeek score - bare DeepSeek score
```

Both answers receive the same question and configured DeepSeek model ID. Gemini assigns the comparison scores in live mode. This design controls the test-taker model, but it does not eliminate judge variance, API changes, prompt sensitivity, or sampling error.

Pi room mode is different. The harness-scoped answer comes from the Pi agent and the baseline comes from DeepSeek. That delta includes both environment and model differences, so it cannot isolate the harness alone.

## Implemented components

- A local collector for `system_prompt.md`, Markdown skills, and JSON tool definitions.
- Draft 7 bundle and full-report schemas.
- A FastAPI service with in-memory sessions, question queues, answer submission, result polling, and dimension-scoped re-evaluation.
- Gemini integrations for question generation, pairwise scoring, and full-file patch generation.
- A bare DeepSeek baseline and a DeepSeek client that receives the collected harness as context.
- Deterministic offline banks for questions, scores, baseline answers, harness answers, and patches.
- A Pi extension with registration, question, answer, re-evaluation, `/temper`, and `/patch` interfaces.
- A React room dashboard updated through server-sent events.
- A small coding mode with one `two_sum` task and five subprocess test cases.

## Evaluation dimensions

| Key | Intended comparison | Current implementation notes |
|---|---|---|
| `instruction_adherence` | Compliance with prompt and skill constraints | Gemini-scored in live mode; fixed scores offline. |
| `tool_accuracy` | Tool selection and argument formation | Tool calls are serialized into answer text for judging. |
| `output_format` | Compliance with requested structure | Gemini-scored in live mode. |
| `skill_trigger` | Appropriate skill activation and non-activation | The service judges the submitted answer, not an independent skill activation trace. |
| `latency_delta` | Harness inference time compared with bare inference time | Uses mean recorded timing when both sides provide it, with a fixed-value fallback when timing is incomplete. |
| `error_recovery` | Recovery from injected tool or output failures | The default branch always labels this dimension structural. |

The service classifies a non-structural initial result as `PASSING` when `delta >= -5`; otherwise it is `NEEDS_PATCH`. During re-evaluation, `delta >= -5` becomes `RESOLVED`. `error_recovery` bypasses that threshold and is always `STRUCTURAL_LIMITATION` on the default branch.

## Patch model

The live patcher asks Gemini for a complete artifact with:

```json
{
  "type": "system_prompt | skill | tool_definition",
  "filename": "path relative to the environment directory",
  "content": "complete replacement file"
}
```

The local and Pi clients apply these as full replacements. This makes re-bundling straightforward, but it also means patches can overwrite files, do not merge concurrent changes, and require human review. The local client does not currently enforce that a returned filename stays inside the environment directory.

## Communication model

The evaluation client makes outbound HTTP requests:

1. `POST /register`
2. `GET /next-question` until a question is available or the session is done
3. `POST /submit-answer` for each question
4. `GET /results` until ready
5. `POST /reeval` after selected replacements are applied

The Pi dashboard additionally uses `POST /rooms/create`, a room-state endpoint, and an SSE stream. Polling keeps the evaluation client independent of inbound connectivity. SSE gives the browser incremental updates without changing the core protocol.

## Deliberate prototype tradeoffs

- Sessions and rooms are process-local dictionaries with no persistence, expiry, or multi-worker coordination.
- Join tokens are one-time, while dashboard keys are reusable and appear in query strings.
- Live generation failures can fall back to deterministic fixture content to keep the demo path moving. Canned live-mode patches include `is_fallback: true`; callers must still distinguish all fallback behavior from live model output.
- The full-report JSON Schema is stricter than the projection returned by `/results`.
- Offline score banks test orchestration and rendering. They do not validate scoring quality or remediation effectiveness.

## What would be needed for robust evaluation

The repository does not currently implement repeated trials, held-out question sets, blinded patch evaluation, confidence intervals, inter-judge agreement, persistent audit logs, or production security controls. Any claim about general harness improvement would require those controls and independently collected live results.
