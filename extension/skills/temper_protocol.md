---
description: TEMPER evaluation protocol — use temper_register, temper_next_question, and temper_submit_answer tools to complete a TEMPER evaluation loop when given a connection block. After the eval, run /patch to apply Gemini's suggested fixes and start re-evaluation automatically.
---

# TEMPER Evaluation Protocol

When you receive a TEMPER connection block, you are being evaluated by TEMPER.
Use the TEMPER tools to complete the eval loop, then run `/patch` for re-evaluation.

## What TEMPER Evaluates

TEMPER tests your *harness* (system prompt, skills, tool definitions), not the base model.
It measures how your harness helps or hurts performance across six dimensions:
instruction_adherence, tool_accuracy, output_format, skill_trigger, latency_delta, error_recovery.

## Step 1 — Build your bundle

Collect everything you are actively using into this shape:
```json
{
  "system_prompt": "<your system instructions, or null>",
  "skills": [{"name": "<skill-name>", "content": "<full skill markdown>"}],
  "tools": [{"name": "<tool-name>", "definition": {}}]
}
```

## Step 2 — Register

Call `temper_register` with `base_url`, `room_id`, `token` (all from the connection block), and your bundle.
Save the `session_id` from the response. The extension saves it automatically to `~/.temper/last_session.json`.

## Step 3 — Answer loop (repeat until done)

1. Call `temper_next_question` with your `session_id`
   - `status: "done"` → stop, all questions answered
   - `status: "not_ready"` → wait 2 seconds and retry
   - `status: "question"` → answer it
2. Answer the question using your normal capabilities. Note how long you took in milliseconds (`latency_ms`).
3. Call `temper_submit_answer` with `session_id`, `question_id`, `answer`, and `latency_ms`.
4. Repeat from step 1.

## Step 4 — Eval complete

Once all questions are submitted, TEMPER generates your report automatically.
The dashboard (at the URL in the connection block) will show live scores as they come in.

## Step 5 — Re-evaluation with /patch

After the eval completes and the Final Report appears on the dashboard:

1. Run `/patch` in this Pi session
2. The extension automatically:
   - Fetches the patches Gemini suggested
   - Applies them to your bundle
   - Starts a re-evaluation on the failing dimensions
   - Tells you the reeval session ID and what to do next
3. Run the answer loop again (step 3) with the new reeval session ID
4. The dashboard will show before/after scores for patched dimensions
