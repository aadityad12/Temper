/**
 * TEMPER Pi Extension
 * ===================
 * Surfaces TEMPER evaluation + re-evaluation tools and commands to the Pi
 * coding agent.
 *
 * Commands:
 *   /temper  — show status and how to start an eval
 *   /patch   — fetch patches from last eval, apply them, start reeval automatically
 *
 * Tools (agent-callable):
 *   temper_register        — POST /register with bundle → session_id
 *   temper_next_question   — GET /next-question → question or done
 *   temper_submit_answer   — POST /submit-answer
 *   temper_reeval          — POST /reeval with updated bundle → reeval_session_id
 *
 * State files (written to ~/.temper/):
 *   last_session.json      — base_url + session_id saved after registration
 *   patched_env/           — patch files written by /patch command
 *
 * Register in ~/.pi/agent/settings.json:
 *   { "extensions": ["/Users/aadityad/Desktop/Aaditya/Personal/ExtraCuricular/Temper/extension/temper.ts"] }
 */

import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const __dir = path.dirname(fileURLToPath(import.meta.url));
const TEMPER_DIR = path.join(os.homedir(), ".temper");
const STATE_FILE = path.join(TEMPER_DIR, "last_session.json");
const PATCHED_ENV_DIR = path.join(TEMPER_DIR, "patched_env");

// ── State helpers ─────────────────────────────────────────────────────────────

interface SessionState {
    base_url: string;
    session_id: string;
    bundle: unknown;
}

function saveState(state: SessionState): void {
    fs.mkdirSync(TEMPER_DIR, { recursive: true });
    fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

function loadState(): SessionState | null {
    try {
        return JSON.parse(fs.readFileSync(STATE_FILE, "utf8")) as SessionState;
    } catch {
        return null;
    }
}

// ── HTTP helper ───────────────────────────────────────────────────────────────

async function httpRequest(
    method: string,
    url: string,
    body?: unknown,
): Promise<{ status: number; data: unknown }> {
    const parsed = new URL(url);
    const payload = body !== undefined ? JSON.stringify(body) : undefined;

    return new Promise((resolve, reject) => {
        const lib = parsed.protocol === "https:" ? require("https") : require("http");
        const options = {
            hostname: parsed.hostname,
            port: parsed.port || (parsed.protocol === "https:" ? 443 : 80),
            path: parsed.pathname + parsed.search,
            method,
            headers: {
                "Content-Type": "application/json",
                ...(payload ? { "Content-Length": Buffer.byteLength(payload) } : {}),
            },
        };
        const req = lib.request(options, (res: any) => {
            const chunks: Buffer[] = [];
            res.on("data", (c: Buffer) => chunks.push(c));
            res.on("end", () => {
                const text = Buffer.concat(chunks).toString();
                let data: unknown;
                try { data = JSON.parse(text); } catch { data = text; }
                resolve({ status: res.statusCode, data });
            });
        });
        req.on("error", reject);
        if (payload) req.write(payload);
        req.end();
    });
}

function textResult(text: string) {
    return { content: [{ type: "text", text }], details: {} };
}

// ── Patch application ─────────────────────────────────────────────────────────

interface Patch {
    type: "system_prompt" | "skill" | "tool_definition";
    filename: string;
    content: string;
}

function applyPatchesToBundle(originalBundle: any, patches: Patch[]): any {
    const bundle = JSON.parse(JSON.stringify(originalBundle));

    for (const patch of patches) {
        if (patch.type === "system_prompt") {
            bundle.system_prompt = patch.content;
        } else if (patch.type === "skill") {
            const name = path.basename(patch.filename, ".md");
            const idx = bundle.skills?.findIndex((s: any) => s.name === name) ?? -1;
            if (idx >= 0) {
                bundle.skills[idx].content = patch.content;
            } else {
                bundle.skills = [...(bundle.skills ?? []), { name, content: patch.content }];
            }
        } else if (patch.type === "tool_definition") {
            const name = path.basename(patch.filename, ".json");
            let definition: unknown;
            try { definition = JSON.parse(patch.content); } catch { definition = patch.content; }
            const idx = bundle.tools?.findIndex((t: any) => t.name === name) ?? -1;
            if (idx >= 0) {
                bundle.tools[idx].definition = definition;
            } else {
                bundle.tools = [...(bundle.tools ?? []), { name, definition }];
            }
        }
    }

    return bundle;
}

function writePatchesToDisk(patches: Patch[]): void {
    fs.mkdirSync(path.join(PATCHED_ENV_DIR, "skills"), { recursive: true });
    fs.mkdirSync(path.join(PATCHED_ENV_DIR, "tools"), { recursive: true });
    for (const patch of patches) {
        const dest = path.join(PATCHED_ENV_DIR, patch.filename);
        fs.mkdirSync(path.dirname(dest), { recursive: true });
        fs.writeFileSync(dest, patch.content);
    }
}

// ── Extension entry point ─────────────────────────────────────────────────────

export default function temperExtension(pi: ExtensionAPI): void {

    // ── Skill discovery ───────────────────────────────────────────────────────
    pi.on("resources_discover", () => {
        const skillDir = path.join(__dir, "skills");
        if (fs.existsSync(skillDir)) return { skillPaths: [skillDir] };
        return {};
    });

    // ── /temper command ───────────────────────────────────────────────────────
    pi.registerCommand("temper", {
        description: "Show TEMPER status and how to start an evaluation",
        handler: async (_args: string, ctx: any) => {
            const state = loadState();
            const lines = [
                "TEMPER extension loaded ✓",
                "Tools: temper_register · temper_next_question · temper_submit_answer · temper_reeval",
                "",
            ];
            if (state) {
                lines.push(`Last session: ${state.session_id} @ ${state.base_url}`);
                lines.push("Run /patch to fetch patches and start a re-evaluation.");
            } else {
                lines.push("No prior session found.");
                lines.push("To start: open the TEMPER dashboard → Create Room → paste the connection block here.");
            }
            ctx.ui.notify(lines.join("\n"), "info");
        },
    });

    // ── /patch command ────────────────────────────────────────────────────────
    pi.registerCommand("patch", {
        description: "Fetch TEMPER patches from the last eval, apply them, and start a re-evaluation automatically",
        handler: async (_args: string, ctx: any) => {
            const state = loadState();
            if (!state) {
                ctx.ui.notify(
                    "No prior TEMPER session found.\nRun an evaluation first by pasting a connection block.",
                    "error",
                );
                return;
            }

            // 1. Fetch results
            ctx.ui.notify(`Fetching results for session ${state.session_id}…`, "info");
            let results: any;
            try {
                const { data } = await httpRequest(
                    "GET",
                    `${state.base_url}/results?session_id=${encodeURIComponent(state.session_id)}`,
                );
                results = data;
            } catch (err) {
                ctx.ui.notify(`Failed to fetch results: ${String(err)}`, "error");
                return;
            }

            if (results.status !== "ready") {
                ctx.ui.notify(`Session not ready yet (status: ${results.status}). Try again in a moment.`, "error");
                return;
            }

            const patches: Patch[] = results.patches ?? [];
            if (patches.length === 0) {
                ctx.ui.notify("No patches suggested by TEMPER for this session.", "info");
                return;
            }

            // 2. Find failing fixable dimensions
            const dims = results.report?.dimensions ?? {};
            const failingDims = Object.entries(dims)
                .filter(([, v]: [string, any]) => v.fixable && v.delta < 0)
                .map(([k]) => k);

            if (failingDims.length === 0) {
                ctx.ui.notify("No fixable failing dimensions found — nothing to re-evaluate.", "info");
                return;
            }

            // 3. Apply patches to disk and to the bundle
            writePatchesToDisk(patches);
            const updatedBundle = applyPatchesToBundle(state.bundle, patches);

            // 4. POST /reeval
            let reevalSessionId: string;
            try {
                const { data } = await httpRequest("POST", `${state.base_url}/reeval`, {
                    session_id: state.session_id,
                    dimensions: failingDims,
                    updated_bundle: updatedBundle,
                });
                reevalSessionId = (data as any).reeval_session_id;
            } catch (err) {
                ctx.ui.notify(`Failed to start reeval: ${String(err)}`, "error");
                return;
            }

            // 5. Save updated state so next /patch knows the latest session
            saveState({ ...state, session_id: reevalSessionId, bundle: updatedBundle });

            // 6. Tell Pi exactly what to do next
            ctx.ui.notify(
                [
                    `✓ ${patches.length} patch(es) applied`,
                    `✓ Re-evaluation started`,
                    `  Reeval session: ${reevalSessionId}`,
                    `  Dimensions: ${failingDims.join(", ")}`,
                    `  Base URL: ${state.base_url}`,
                    "",
                    "Now run the eval loop:",
                    `  1. Call temper_next_question with base_url="${state.base_url}" and session_id="${reevalSessionId}"`,
                    "  2. Answer each question using your normal capabilities",
                    `  3. Call temper_submit_answer with the session_id, question_id, answer, and latency_ms`,
                    "  4. Repeat until status is 'done'",
                ].join("\n"),
                "info",
            );
        },
    });

    // ── Tools ─────────────────────────────────────────────────────────────────
    const register = (pi as any).registerTool;
    if (typeof register !== "function") return;

    // temper_register — POST /register
    register.call(pi, {
        name: "temper_register",
        label: "TEMPER register",
        description:
            "Register with the TEMPER server. Provide the base_url, room_id, token from the connection block, and your environment bundle. Returns a session_id. Also saves state for /patch to use later.",
        parameters: {
            type: "object",
            properties: {
                base_url: { type: "string", description: "TEMPER server base URL, e.g. https://temper-2dwph.ondigitalocean.app" },
                room_id:  { type: "string", description: "Room ID from the connection block" },
                token:    { type: "string", description: "One-time join token from the connection block" },
                bundle:   { type: "object", description: "Environment bundle: {system_prompt, skills: [{name, content}], tools: [{name, definition}]}" },
            },
            required: ["base_url", "room_id", "token", "bundle"],
        },
        execute: async (args: { base_url: string; room_id: string; token: string; bundle: unknown }) => {
            try {
                const { status, data } = await httpRequest("POST", `${args.base_url}/register`, {
                    room_id: args.room_id,
                    token:   args.token,
                    bundle:  args.bundle,
                });
                const session_id = (data as any)?.session_id;
                if (session_id) {
                    saveState({ base_url: args.base_url, session_id, bundle: args.bundle });
                }
                return textResult(JSON.stringify({ status, data }, null, 2));
            } catch (err) {
                return textResult(`temper_register error: ${String(err)}`);
            }
        },
    });

    // temper_next_question — GET /next-question
    register.call(pi, {
        name: "temper_next_question",
        label: "TEMPER next question",
        description:
            "Fetch the next question from TEMPER. Returns {status: 'question', question_id, dimension, prompt} when ready, {status: 'not_ready'} if still generating (wait 2s and retry), or {status: 'done'} when finished.",
        parameters: {
            type: "object",
            properties: {
                base_url:   { type: "string", description: "TEMPER server base URL" },
                session_id: { type: "string", description: "Session ID from temper_register or temper_reeval" },
            },
            required: ["base_url", "session_id"],
        },
        execute: async (args: { base_url: string; session_id: string }) => {
            try {
                const { status, data } = await httpRequest(
                    "GET",
                    `${args.base_url}/next-question?session_id=${encodeURIComponent(args.session_id)}`,
                );
                return textResult(JSON.stringify({ status, data }, null, 2));
            } catch (err) {
                return textResult(`temper_next_question error: ${String(err)}`);
            }
        },
    });

    // temper_submit_answer — POST /submit-answer
    register.call(pi, {
        name: "temper_submit_answer",
        label: "TEMPER submit answer",
        description:
            "Submit your answer to the current TEMPER question. Provide session_id, question_id, answer, and latency_ms (wall-clock ms for inference only).",
        parameters: {
            type: "object",
            properties: {
                base_url:      { type: "string", description: "TEMPER server base URL" },
                session_id:    { type: "string", description: "Session ID" },
                question_id:   { type: "string", description: "Question ID from temper_next_question" },
                answer:        { type: "string", description: "Your answer to the question" },
                latency_ms:    { type: "number", description: "Milliseconds taken to produce the answer" },
                input_tokens:  { type: "number", description: "Input token count (optional)" },
                output_tokens: { type: "number", description: "Output token count (optional)" },
            },
            required: ["base_url", "session_id", "question_id", "answer", "latency_ms"],
        },
        execute: async (args: {
            base_url: string; session_id: string; question_id: string;
            answer: string; latency_ms: number; input_tokens?: number; output_tokens?: number;
        }) => {
            try {
                const { status, data } = await httpRequest("POST", `${args.base_url}/submit-answer`, {
                    session_id:    args.session_id,
                    question_id:   args.question_id,
                    answer:        args.answer,
                    latency_ms:    args.latency_ms,
                    input_tokens:  args.input_tokens,
                    output_tokens: args.output_tokens,
                });
                return textResult(JSON.stringify({ status, data }, null, 2));
            } catch (err) {
                return textResult(`temper_submit_answer error: ${String(err)}`);
            }
        },
    });

    // temper_reeval — POST /reeval
    register.call(pi, {
        name: "temper_reeval",
        label: "TEMPER reeval",
        description:
            "Start a TEMPER re-evaluation with a patched bundle. Provide the original session_id, the failing dimensions to re-test, and the updated bundle. Returns a reeval_session_id — use that with temper_next_question and temper_submit_answer to run the loop.",
        parameters: {
            type: "object",
            properties: {
                base_url:        { type: "string", description: "TEMPER server base URL" },
                session_id:      { type: "string", description: "Original eval session ID" },
                dimensions:      { type: "array",  items: { type: "string" }, description: "Failing dimensions to re-evaluate, e.g. ['instruction_adherence', 'skill_trigger']" },
                updated_bundle:  { type: "object", description: "The patched environment bundle with fixes applied" },
            },
            required: ["base_url", "session_id", "dimensions", "updated_bundle"],
        },
        execute: async (args: { base_url: string; session_id: string; dimensions: string[]; updated_bundle: unknown }) => {
            try {
                const { status, data } = await httpRequest("POST", `${args.base_url}/reeval`, {
                    session_id:     args.session_id,
                    dimensions:     args.dimensions,
                    updated_bundle: args.updated_bundle,
                });
                const reevalId = (data as any)?.reeval_session_id;
                if (reevalId) {
                    const prev = loadState();
                    if (prev) saveState({ ...prev, session_id: reevalId, bundle: args.updated_bundle });
                }
                return textResult(JSON.stringify({ status, data }, null, 2));
            } catch (err) {
                return textResult(`temper_reeval error: ${String(err)}`);
            }
        },
    });
}
