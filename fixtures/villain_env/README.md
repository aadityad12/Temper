# Seeded customer-support fixture

This directory is a synthetic harness for deterministic TEMPER tests. It is not a deployed customer environment. The files contain deliberate prompt, skill, and tool-definition defects that exercise each result path.

## Seeded defects

| Dimension | Fixture condition | Expected offline status |
|---|---|---|
| Instruction adherence | `system_prompt.md` requires formal language, then asks the model to mirror a customer's casual tone. | `NEEDS_PATCH` |
| Tool accuracy | `lookup_order.json` requires a string ID but defines no pattern or example. `create_ticket.json` lacks enums for priority and category. | `NEEDS_PATCH` |
| Output format | The harness defines no global structured-output requirement. | `PASSING` |
| Skill trigger | `escalate.md` triggers on any money reference, including ordinary pricing questions. `lookup_order.md` uses a broad account or order trigger. | `NEEDS_PATCH` |
| Latency delta | The local harness prepends every collected skill and tool definition to every question. | `NEEDS_PATCH` |
| Error recovery | Scripted failure prompts exercise the structural result path. | `STRUCTURAL_LIMITATION` |

## Offline methodology

`CLOUD_OFFLINE=true` does not derive scores from the fixture. It uses constants in `cloud/judge.py` and canned patches in `cloud/patcher.py`.

The initial run contains 12 questions, two for each dimension. The scripted scores are:

| Dimension | Baseline | Harness | Delta |
|---|---:|---:|---:|
| `instruction_adherence` | 71 | 44 | -27 |
| `tool_accuracy` | 72 | 31 | -41 |
| `output_format` | 88 | 85 | -3 |
| `skill_trigger` | 60 | 52 | -8 |
| `latency_delta` | 90 | 74 | -16 |
| `error_recovery` | 38 | 35 | -3 |

The integration flow applies three canned files: a replacement system prompt, `skills/lookup_order.md`, and `tools/lookup_order.json`. It then serves two questions for each of the four dimensions marked patchable. The re-evaluation score bank moves instruction adherence from 44 to 82 and tool accuracy from 31 to 79; those are the two movements asserted by `local/test_integration.py`.

These values provide stable regression coverage for the protocol, patch writes, renderer, and assertions. They are not a live benchmark, do not estimate model error rates, and should not be reported as measured remediation results.

## Safe use

The integration and Makefile test commands restore this directory with `git checkout`. Do not run them with uncommitted changes here. Patch commands overwrite target files, so review `local/last_patches.json` before applying live output to another environment.
