---
description: TEMPER evaluation protocol — use temper_register, temper_next_question, and temper_submit_answer tools to complete a TEMPER evaluation loop when given a connection block.
---

# TEMPER Evaluation Protocol

When you receive a TEMPER connection block, you are being evaluated by TEMPER.
Use the TEMPER tools below to complete the loop — do not use curl manually.

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

Call `temper_register` with base_url, room_id, token, and your bundle.
Save the `session_id` from the response.

## Step 3 — Answer loop (repeat until done)

1. Call `temper_next_question` with your session_id
   - `status: "done"` → stop, you are finished
   - `status: "not_ready"` → wait 2 seconds and retry
   - `status: "question"` → answer it
2. Answer the question using your normal capabilities. Note how long you took (latency_ms).
3. Call `temper_submit_answer` with session_id, question_id, answer, and latency_ms.
4. Repeat from step 1.

## Step 4 — Done

Once all questions are submitted, TEMPER generates your report automatically.
The dashboard at http://localhost:8001 will show live scores as they come in.
