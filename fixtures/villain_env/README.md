# Villain Environment — Answer Key

A realistic customer support deployment for "Acme SaaS" seeded with deliberate,
diagnosable flaws. Every TEMPER demo number traces back to this file.

---

## Scenario

Acme SaaS is a B2B project management company. This is their Claude Code harness
for handling inbound customer support. A real team shipped this — it looked fine
in manual testing. TEMPER catches what they missed.

---

## Seeded Flaws by Dimension

### 1. Instruction Adherence — NEEDS_PATCH

**Flaw A — Direct contradiction in `system_prompt.md`:**
- Line: *"Always respond in formal, professional English."*
- Line: *"Adapt your tone to match the customer's communication style — if they write casually, mirror their energy and be more relaxed."*

These two instructions are directly contradictory. A casual customer greeting causes
the model to switch to informal language, violating the formal-English rule. In practice
this happens on roughly 60% of opening messages.

**Flaw B — Pricing rule contradiction in `system_prompt.md`:**
- Line: *"Never share internal pricing structures … under any circumstances."*
- Then immediately: a published pricing table (Starter $29, Pro $99, Enterprise).

The model correctly reads "never reveal pricing" and then sees pricing listed in
the same prompt. This ambiguity causes inconsistent responses to pricing questions —
sometimes the model refuses to quote prices, sometimes it cites them.

**Flaw C — Padding dilutes behavioral instructions:**
The final paragraph of `system_prompt.md` is pure culture copy with no behavioral
instruction value. It adds tokens and noise that weakens instruction signal.

**Expected scores:** baseline ~71, harness ~44, Δ −27
**Fix type:** `system_prompt` — resolve contradiction (pick formal over adaptive),
clarify that the pricing table IS shareable (it is published), trim padding.
**Post-patch target:** harness ~82

---

### 2. Tool Call Accuracy — NEEDS_PATCH

**Flaw — `lookup_order.json` missing format constraint on `order_id`:**

The `order_id` parameter has type `string` and a vague description: "The customer's
order or subscription ID." No format, no pattern, no example.

Real Acme order IDs follow the format `ACM-YYYYMMDD-XXXXX` (e.g. `ACM-20240615-A4F92`).
Without a constraint, the model generates plausible-but-wrong IDs like `ORD-123`,
`order_12345`, or `SUB-456`, which all fail at the API layer. This happens ~70% of
the time when the customer quotes only a partial reference.

**Flaw — `create_ticket.json` missing enum on `priority` and `category`:**

`priority` accepts any string but the API only accepts `low | medium | high | critical`.
`category` accepts any string but the API only accepts `billing | technical | account | other`.
The model hallucinates values like `"urgent"` and `"subscription"` which cause silent
API failures.

**Expected scores:** baseline ~72, harness ~31, Δ −41
**Fix type:** `tool_definition` + `skill` (usage patterns with format examples)
**Post-patch target:** harness ~79

---

### 3. Output Format Compliance — PASSING

No structured output requirement is defined in the harness. The model's default
prose responses are acceptable. This dimension should score near-neutral (harness
neither helps nor hurts).

**Expected scores:** baseline ~88, harness ~85, Δ −3
**Status:** PASSING — no patch needed.

---

### 4. Skill Trigger Precision — NEEDS_PATCH

**Flaw A — `escalate.md` trigger is too broad:**

Trigger includes: *"Billing, payment, invoice, charge, or money."*

This fires on general pricing questions ("How much does the Pro plan cost?") which
should NOT escalate — just answer with the published pricing. The false-positive
rate on pricing questions is ~80%, causing unnecessary escalations that frustrate
customers and overload the specialist queue.

**Flaw B — `lookup_order.md` trigger is too vague:**

*"When a customer has a question about their order or account"* misses implicit
signals like "my invoice is wrong" (billing + order), "I was charged twice" (billing
dispute that also needs order lookup), or "my subscription renewal failed" (clearly
an order issue but framed as a technical problem).

**Expected scores:** baseline ~60, harness ~52, Δ −8
**Fix type:** `skill` — tighten escalate trigger (billing disputes only, not pricing
questions); broaden lookup_order trigger with explicit signal examples.
**Post-patch target:** harness ~71

---

### 5. Latency Delta — NEEDS_PATCH

**Flaw — All skills loaded regardless of relevance:**

The harness prepends both skill files on every call, even when neither is needed
(e.g. a simple "what are your support hours?" question loads escalation and order
lookup context). This adds ~340ms of overhead per call from token inflation alone.

The final padding paragraph in `system_prompt.md` (~80 tokens) contributes
additionally with no behavioral return.

**Expected scores:** baseline latency ~410ms, harness latency ~750ms → score 90 vs 74, Δ −16
**Fix type:** `skill` — conditional skill loading (load escalate only when billing
signals present, load lookup_order only when order signals present); trim padding.
**Post-patch target:** harness latency ~480ms

---

### 6. Error Recovery Rate — STRUCTURAL_LIMITATION

**Design intent:** this dimension is intentionally unfixable at the harness level.

**What is tested:** when `lookup_order` returns a tool error (malformed response,
API timeout, 404 for unknown order), does the harness help the model self-correct?

**Why it is structural:** the model consistently fails to recognise that its own
tool call caused the error. It either retries with the same malformed `order_id`
or presents the raw API error to the customer. Adding a recovery-path SKILL.md
helps marginally but cannot overcome the model's inability to inspect and correct
its own prior tool calls mid-turn.

The genuine fix is application-layer: validate `order_id` format before the tool
call (outside the LLM), or switch to a model with stronger tool-call self-correction.
Neither is a harness-level skill.

**Expected scores:** baseline ~38, harness ~35, Δ −3
**Post-patch (after SKILL.md recovery paths added):** harness ~37 (no meaningful movement)
**Status:** STRUCTURAL_LIMITATION
**Structural reason:** *"Self-correction of failed tool calls requires the model to
identify its own output as the error source. This is a model-capability ceiling.
Fix: add order_id validation in application code before the LLM call, or upgrade
to a model with stronger tool-use self-correction."*

---

## Expected Demo Numbers (pre-patch)

| Dimension             | Baseline | Harness | Δ    | Status              |
|-----------------------|----------|---------|------|---------------------|
| instruction_adherence | 71       | 44      | −27  | NEEDS_PATCH         |
| tool_accuracy         | 72       | 31      | −41  | NEEDS_PATCH         |
| output_format         | 88       | 85      | −3   | PASSING             |
| skill_trigger         | 60       | 52      | −8   | NEEDS_PATCH         |
| latency_delta         | 90       | 74      | −16  | NEEDS_PATCH         |
| error_recovery        | 38       | 35      | −3   | STRUCTURAL_LIMITATION |

## Expected Demo Numbers (post-patch, patched dimensions only)

| Dimension             | Pre-patch | Post-patch | Movement |
|-----------------------|-----------|------------|----------|
| tool_accuracy         | 31        | 79         | +48 → RESOLVED |
| instruction_adherence | 44        | 82         | +38 → RESOLVED |
| error_recovery        | 35        | 37         | +2  → STRUCTURAL_LIMITATION |

---

## Validation Checklist

For Dev 2 (cloud layer): when Gemini evaluates this environment, the scores should
land within ±10 of the numbers above. If they don't:

- [ ] Check that the contradiction probes are testing the specific lines noted above
- [ ] Check that tool_accuracy probes use order IDs that expose the missing format constraint
- [ ] Check that skill_trigger probes include explicit pricing questions (should NOT escalate)
- [ ] Confirm error_recovery probes inject tool-call failures, not just ambiguous inputs

The direction of the delta matters more than the exact score. Every dimension except
`output_format` should show a negative delta pre-patch.
