---
name: dreaming
description: "Use when consolidating conversation logs into long-term invariants, updating domain memories, running cold-start historical ingestion, resolving memory contradictions, reviewing memory proposals, or scheduling nightly consolidation."
category: memory
risk: moderate
source: first-party
date_added: "2026-09-27"
metadata:
  triggers: dreaming, consolidate memory, cold start memory, memory proposals, invariant extraction, sync memory
---

# Dreaming: Autonomous Long-Term Memory Consolidation

Master procedural runbook for extracting durable domain invariants, user axioms, and system guardrails from conversation transcripts, maintaining an ultra-lean memory manifest, and superseding outdated rules.

## When to Use

- Executing scheduled nightly consolidation (daily 3:00 AM daemon).
- Bootstrapping memory from historical sessions when cold-start has not run.
- Consolidating recent conversation transcripts after intense development sessions.
- Reviewing, approving, or editing staged candidate memory proposals.
- Resolving dialectic contradictions when technical decisions or requirements evolve.
- Auditing memory files for line budget ceilings or concept overlap deduplication.

## When NOT to Use

- Making routine code changes or running tests inside a project repository.
- Storing temporary debugging notes, one-off commands, or ephemeral session logs.
- Modifying files inside user project git trees (violates Zero Repository Pollution).

---

## Procedural Workflow

```
[0. First-Run Check] ──(Not Done)──> [Cold-Start Map-Reduce Backfill]
         │ (Done)
[1. Query Root Sessions] ──(Since Watermark, nesting_depth == 0)
         │
[2. Stream Transcripts] ──(Filter USER_INPUT & PLANNER, Strip Multi-MB Payloads)
         │
[3. Load Memory State] ──(Read dreaming/index.md & active domain files)
         │
[4. 4-Tier Classification] ──(Tier 1 Axioms, Tier 2 Invariants, Tier 3 Realities, Tier 4 Noise)
         │
[5. Keyed Invariant Formatting] ──(<!-- INVARIANT_KEY --> schema with Negative Constraints)
         │
[6. Contradiction Resolution] ──(Archive superseded invariants to dreaming/archive/superseded.md)
         │
[7. Semantic Deduplication] ──(>= 60% overlap merges into existing domain)
         │
[8. Turbo / Standard Execution] ──(Turbo: >= 0.9 auto-commit; < 0.9 stage to proposals/)
         │
[9. Advance Watermark] ──(Atomic state update in dreaming/.state.json)
```

---

### Step 0: First-Run Check (Cold-Start Auto-Bootstrap)

1. Check if `dreaming/.state.json` exists in `~/.gemini/config/` (or current dreaming root) and verify whether `cold_start_completed` is `true`.
2. If `dreaming/.state.json` is missing or `cold_start_completed` is `false`:
   - Execute the 3-stage Map-Reduce cold-start pipeline across all historical root sessions:
     ```powershell
     python -m scripts.cold_start
     ```
   - This deterministically anchors workspace URIs (Stage 1), distills unanchored sessions into entity/topic candidates (Stage 2), clusters entities into `people/`, `domains/`, and `projects/` namespaces, mints baseline memory files, writes the master manifest `dreaming/index.md`, and persists `cold_start_completed: true` in `dreaming/.state.json`.
3. If cold-start is already completed, proceed directly to incremental consolidation.

---

### Step 1: Query Recent Root Sessions

1. Query `conversation_summaries.db` using the safe read-only connector:
   - Must use read-only URI mode (`file:<path>?mode=ro`) with WAL support and a 5000ms busy timeout.
   - Filter strictly for root sessions: `nesting_depth == 0`. Subagents and nested worker conversations (`nesting_depth > 0`) are excluded to avoid capturing intermediate orchestration noise.
   - Filter by timestamp: `last_modified_time > watermark` using the `last_consolidated_timestamp` from `dreaming/.state.json` (or past 24 hours if uninitialized).
   - Filter out in-flight or empty sessions: skip sessions where `status == 'CASCADE_RUN_STATUS_RUNNING'` or `step_count == 0`.
2. If zero qualifying sessions are returned:
   - Conclude consolidation quietly: log `"Nothing to consolidate; watermark current."` and exit.

---

### Step 2: Stream Compact Transcripts (Payload Stripping & Watermark Partitioning)

1. For each qualifying session ID, locate and read `brain/<session_id>/.system_generated/logs/transcript.jsonl` using `extract_compact_transcript(session_id, watermark=last_consolidated_timestamp, prior_context_turns=4)`.
2. Extract high-signal conversational turns and parse literal `created_at` ISO timestamps on each user and agent turn:
   - `type == 'USER_INPUT'`: User instructions, architectural requirements, feedback, corrections, and explicit preferences.
   - `type == 'PLANNER_RESPONSE'`: Agent thinking traces, formulated plans, and architectural rationale.
   - `tool_calls` summary metadata: Tool names and concise summaries (`toolAction`, `toolSummary`).
3. **Partitioned Transcript Utilization**:
   - Utilize `transcript.render_partitioned_markdown()` to obtain a clean, structured Markdown transcript partitioned into:
     - `### Prior Context`: Historical turns on or before the watermark (`created_at <= watermark`), strictly bounded to the most recent `prior_context_turns` (default 4) to eliminate token bloat.
     - `### New Activity`: Recent turns occurring strictly after the watermark (`created_at > watermark`).
4. **Multi-MB Payload Stripping Invariant**:
   - Explicitly discard raw tool output blocks (`type == 'GENERIC'`), large stdout/stderr streams, compiler diffs, image bytes, and code contents exceeding 1 KB.
   - Reduce multi-megabyte raw execution logs to compact (<30 KB) intent and decision records.

---

### Step 3: Load Context & Memory State

1. Read the Master Manifest `dreaming/index.md` via `view_file` to inspect registered domains, people, project workspace URIs, and trigger aliases.
2. Read active memory files related to the sessions being analyzed (e.g. `dreaming/memories/<slug>.md`, `dreaming/memories/preferences.md`, `dreaming/memories/guardrails.md`).
3. Read `~/.gemini/config/AGENTS.md` via `view_file` to load the active global agent constitution and rules.
4. Note current file line counts to ensure additions will not breach per-file line ceilings.

---

### Step 4: Apply 4-Tier Epistemic Classification

Evaluate candidate signals against the 4-Tier Epistemic Classification Model:

| Tier | Epistemic Class | Signal Criteria | Destination File | Line Budget |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1** | **User Interaction Axioms** | Explicit corrections on communication tone, depth, persona, problem-solving posture | `memories/preferences.md` | Max 1,000 lines |
| **Tier 2** | **Project & Domain Invariants** | Architectural boundaries, non-negotiable data models, negative constraints, hardware bindings | `memories/<slug>.md` | Max 1,000 lines per file |
| **Tier 3** | **Environment Realities** | Host system idiosyncrasies, OS shell quirks, runtime version boundaries, tool defects | `memories/guardrails.md` | Max 1,000 lines |
| **Tier 4** | **Transient Operational Noise** | Ephemeral debugging flags, temporary workarounds, single-task work items | **DISCARDED** | 0 lines |

#### Partitioned Context Distillation Rules:
- **Restrict Active Distillation Strictly to `### New Activity`**: Invariant discovery, candidate rule extraction, and rule modifications must be derived strictly from turns within the `### New Activity` section.
- **`### Prior Context` Strictly for Reference & Grounding**: The `### Prior Context` section must be used solely for background context, pronoun resolution (e.g. resolving what "it" or "that service" refers to), and conversational grounding. NEVER extract new invariants or update timestamps based on turns in `### Prior Context`.
- **Preserve Untouched Existing Invariants**: Existing invariants in active memory files that were not reaffirmed or modified in the `### New Activity` section MUST be preserved untouched. Do NOT delete or re-date existing invariants simply because the new activity did not mention them.

#### Critical Rule on Tier 4 Semantic Filtering:
- **Filtering is a SEMANTIC JUDGMENT, NOT a naive keyword blocklist.**
- Do NOT reject signals simply because they contain colloquial words like *"today"*, *"for now"*, or *"temporarily"*. For example, *"I've been using mmap for now and it works great"* expresses a permanent architectural decision using casual phrasing.
- Distinguish true temporary workarounds (e.g., *"skip test X today"*, *"hardcode IP 192.168.1.50 until router reboots"*) from durable invariants. Discard only genuinely time-bounded items with no long-term architectural value.

---

### Step 5: Keyed Invariant Schema Standard

Every Tier 2 project or domain invariant must be formatted according to the standardized Keyed Invariant Schema:

```markdown
<!-- INVARIANT_KEY: <namespace>.<identifier> -->
<!-- LAST_CONFIRMED: YYYY-MM-DD (Session: <session_id>) -->
<!-- SUPERSEDES: <optional_prior_invariant_key> -->
- **Target**: `<code_component_or_entity>`
  **Invariant**: `<positive_assertion_of_rule>`
  **Negative Constraint**: `<explicitly_forbidden_pattern>`
  **Rationale**: `<causal_justification_or_prevented_failure_mode>`
```

#### Field Standards:
- `INVARIANT_KEY`: Unique hierarchical identifier in snake_case (e.g., `project_name.component_boundary`, `infrastructure.service_restart_guard`).
- `LAST_CONFIRMED`: ISO date (`YYYY-MM-DD`) and short conversation ID where this invariant was verified or restated (e.g. `YYYY-MM-DD (Session: <session_id>)`). **Literal Timestamp Anchoring**: Strictly anchor this date to the literal turn date (`created_at`) from the transcript where the invariant was affirmed or stated. NEVER default to today's date or the consolidation execution date.
- `SUPERSEDES`: Prior invariant key being deprecated (omitted if new invariant).
- `Target`: The exact component, class, service, interface, or conceptual entity.
- `Invariant`: Clear, imperative statement of what must be true.
- `Negative Constraint`: Explicit prohibition of what must NOT be done. Essential for overriding default LLM training biases.
- `Rationale`: Why the invariant exists and what regression it prevents.

---

### Step 6: Dialectic Contradiction Supersession

When an extracted candidate invariant conflicts with or updates an existing rule:
1. **Match Key & Semantics**: Match existing `<!-- INVARIANT_KEY -->` tags and check for semantic conflict.
2. **Strict Coexistence Ban**: Contradictory sibling rules must NEVER coexist in active memory files. Sibling ambiguity causes agents to oscillate between conflicting behaviors.
3. **Dialectic Archival Lifecycle**:
   - Remove the retired invariant from the active domain or project file.
   - Append the retired rule to `dreaming/archive/superseded.md` under a structured archival block:
     ```markdown
     ### [SUPERSEDED: YYYY-MM-DD] <namespace>.<identifier>
     - **Retired Rule**: `<verbatim_prior_invariant>`
     - **Superseded By**: `<new_invariant_key>`
     - **Session Evidence**: Session `<session_id>`
     - **Dialectic Rationale**: `<explanation_of_why_user_or_architecture_evolved>`
     ```
   - Add `<!-- SUPERSEDES: <old_invariant_key> -->` to the new invariant written to active memory.

---

### Step 7: Concept Overlap Deduplication & Anti-Fragmentation

1. If a candidate invariant suggests minting a new memory file, evaluate semantic overlap against existing files in `dreaming/index.md`.
2. **Concept Overlap Threshold (>= 60%)**:
   - If candidate concept has $\ge 60\%$ semantic overlap with an existing domain (e.g. `home-assistant-sensors.md` vs `smart-home.md`), **do NOT create a new file**.
   - Consolidate the candidate into the existing file.
   - If new keywords or aliases emerge, append them to the existing entry's `Aliases: [...]` in `dreaming/index.md`.

---

### Step 7b: Global Rule Deduplication & Constitutional Amendment Gate (AGENTS.md)

1. **Deduplication against `AGENTS.md`**:
   - Compare all candidate invariants against `~/.gemini/config/AGENTS.md`.
   - If an invariant is already explicitly codified or enforced by an existing global rule in `AGENTS.md` (e.g. Git Task Completion, PowerShell Execution Safety, The Stranger Test, Skill Dispatch), **DISCARD IT IMMEDIATELY**.
   - Do NOT duplicate global rules into `memories/preferences.md` or `memories/guardrails.md`.

2. **Constitutional Amendment Proposal Gate (Strict Human-in-the-Loop)**:
   - If transcript evidence reveals that a technical decision, user correction, or environment reality **refines, contradicts, or deprecates** an active rule in `AGENTS.md`, or introduces a new universal operational constraint:
     - **STRICT COGNITIVE PROHIBITION**: The Dreamer MUST NEVER autonomously edit or auto-commit changes to `~/.gemini/config/AGENTS.md`, even in Turbo Mode. `AGENTS.md` is the global system constitution.
     - **STAGE FORMAL PROPOSAL**: Create a structured proposal file in `~/.gemini/config/dreaming/proposals/YYYY-MM-DD-agents-md.md`:
       ```markdown
       # AGENTS.md Constitutional Amendment Proposal
       - **Target File**: `~/.gemini/config/AGENTS.md`
       - **Session Evidence**: Session `<session_id>` (Turn <step_index>, <literal_created_at>)
       - **Rationale**: `<concise_explanation_of_why_user_or_system_evolved>`
       - **Status**: PENDING_HUMAN_APPROVAL

       ### Proposed Diff:
       ```diff
       --- a/AGENTS.md
       +++ b/AGENTS.md
       @@ ... @@
       - <old_rule_line>
       + <new_refined_rule_line>
       ```
       ```
     - **MORNING SUMMARY REPORT**: In the morning summary card, prominently report:
       `"⚠️ Constitutional Amendment Staged: AGENTS.md update proposed from Session <session_id>. Requires human review before applying."`

---

### Step 8: Execution Mode (Turbo Mode vs Standard Mode)

Read `turbo_mode` from `dreaming/.state.json` (defaults to `true`):

#### 1. Turbo Mode (`turbo_mode: true` — Autonomous Execution):
- **Confidence Gating ($\ge 0.9$)**: Candidate invariants with high confidence ($\ge 0.9$) and clear evidentiary backing are auto-committed directly to target memory files.
- **Constitutional Immunity**: `~/.gemini/config/AGENTS.md` is strictly immune to Turbo Mode auto-commits. Any amendment touching `AGENTS.md` MUST be staged to `proposals/` for human approval regardless of confidence score.
- **Ambiguity Staging ($< 0.9$)**: Borderline or ambiguous candidates are staged to `dreaming/proposals/YYYY-MM-DD.md` for human review.
- **Line Budget Enforcement**: Verify file length before committing. If adding an invariant would exceed the line ceiling (1,000 lines per file), **refuse auto-commit** and stage a compaction proposal in `dreaming/proposals/YYYY-MM-DD.md`.
- **Atomic Git Commits in `agy-core`**:
  - Execute a clean, atomic conventional commit in `~/.gemini/config/` for each consolidated domain:
    ```bash
    git commit -m "dream(<slug>): add <identifier> invariant (Session: <session_id>)"
    ```
  - Enables instant one-command rollbacks: `git revert <sha>`.
- **Non-Blocking Morning Summary**: At the start of the next morning session, report:
  `"Overnight Dream: Auto-committed N invariants to <slug>.md. Run git log -3 dreaming/ to review."` (and highlight any pending `AGENTS.md` proposals).

#### 2. Standard Mode (`turbo_mode: false` — Human-in-the-Loop):
- Stage all candidate additions, modifications, and supersessions to `dreaming/proposals/YYYY-MM-DD.md`.
- Present an interactive review card on the first morning session for user approval before modifying active memory.

---

### Step 9: Watermark Advancement & State Persistence

1. Update `dreaming/.state.json`:
   - Set `last_consolidated_timestamp` to the latest session modification timestamp.
   - Record `last_consolidated_session_id`.
   - Append processed session IDs to `processed_session_ids`.
   - Update consolidation stats (scanned sessions, extracted invariants, auto-committed counts).
2. Write state atomically using `save_state_atomic` (`.tmp` write followed by atomic `os.replace`) to protect against corruption during unexpected termination.

---

## Scheduled Cron Job Configuration

Antigravity executes nightly dreaming via the background `schedule` tool:

```json
{
  "CronExpression": "0 3 * * *",
  "IsDaemon": true,
  "Prompt": "You are the Antigravity Dreamer. Your mission is to consolidate conversation sessions into long-term memory using the dreaming skill. Follow these steps strictly:\n0. FIRST-RUN CHECK: Check if ~/.gemini/config/dreaming/.state.json exists and cold_start_completed is true. If false or missing, execute the cold-start backfill via scripts.cold_start across all historical root sessions, synthesize baseline memory files, write dreaming/index.md, record state, and commit.\n1. INCREMENTAL DISCOVERY: Query root sessions (nesting_depth == 0) in conversation_summaries.db modified since the watermark timestamp in dreaming/.state.json.\n2. TRANSCRIPT EXTRACTION: For each qualifying session, extract partitioned turns using dream_helpers.py with watermark, distilling invariants strictly from New Activity while using Prior Context for reference.\n3. SYNTHESIS & CLASSIFICATION: Load dreaming/index.md and relevant domain files. Apply the 4-Tier Epistemic Classification and Keyed Invariant Schema. Discard transient operational noise using semantic judgment.\n4. CONTRADICTION & SUPERSESSION: Match existing INVARIANT_KEY tags. If technical decisions evolved, archive superseded rules to dreaming/archive/superseded.md.\n5. COMMIT OR STAGE: In Turbo Mode (default), auto-commit high-confidence (>= 0.9) invariants directly with atomic git commits in agy-core, and stage ambiguous items to dreaming/proposals/YYYY-MM-DD.md. In Standard Mode, stage all proposals.\n6. WATERMARK: Advance the watermark in dreaming/.state.json via atomic write. If there is nothing meaningful to consolidate, exit quietly."
}
```

---

## Operational Guardrails & Invariants

1. **Zero Repository Pollution**: The Dreamer must NEVER create, edit, or delete files inside user project workspaces or user git repositories. All persistent memory lives in `~/.gemini/config/dreaming/`.
2. **Safe SQLite Access**: Always open `conversation_summaries.db` in read-only mode (`?mode=ro`). Never attempt write operations against the Antigravity runtime database.
3. **Resilience to Corrupted Logs**: Missing sessions, broken JSONL lines, or empty files must be logged and bypassed without halting consolidation.
4. **Clean Rollbacks**: Every change committed in Turbo Mode must be an atomic git commit in `agy-core` so any modification can be cleanly reverted with `git revert`.
5. **Turn-Level Watermark Partitioning**: Incremental consolidation must always pass the state watermark and bound historical context. Invariant extraction must operate exclusively on `### New Activity`, while `### Prior Context` provides bounded reference without generating rules.
6. **Literal Turn Date Anchoring**: `<!-- LAST_CONFIRMED: YYYY-MM-DD -->` must strictly match the literal `created_at` date of the turn where the invariant was affirmed. Never smudge timestamps to today's execution date.
