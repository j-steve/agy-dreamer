---
name: dreaming
description: "Use when consolidating conversation logs into long-term Markdown memories, updating domain or project memory files, pruning stale or repo-redundant entries, reviewing staged proposals, or configuring scheduled consolidation."
category: memory
risk: moderate
source: first-party
date_added: "2026-09-27"
metadata:
  triggers: dreaming, consolidate memory, cold start memory, memory proposals, deep dream, sync memory
---

# Dreaming (v2): Autonomous Long-Term Memory Consolidation

Operational runbook for distilling conversation transcripts into concise, scannable Markdown memory files across people, life domains, and engineering projects while keeping host watermarks isolated and repositories free of clutter.

## Objectives & Boundaries

- **Purpose**: Help Antigravity remember durable facts, preferences, external topology, hardware/environment quirks, and non-obvious architectural decisions across sessions and across nodes.
- **Zero Repository Pollution**: All memory files and staged proposals live in `~/.gemini/config/dreaming/` (tracked in `agy-core`). Do not write memory metadata into user project repositories.
- **Host-Local Watermarks**: `dreaming/.state.json` is gitignored per-host runtime state so each node (Windows workstation and Proxmox CT 102) tracks its own `conversation_summaries.db` watermark independently without cross-host clobbering.
- **Secret Hygiene**: Route API keys, tokens, webhook secrets, passwords, and government IDs (passport numbers, SSNs, account numbers) to gitignored `~/.gemini/config/credentials/<service>.json` and sync via `python ~/.gemini/config/scripts/sync_credentials.py push`. Reference only the credential file path and key name inside `dreaming/memories/*.md`.

---

## 1. The Repo-Blindness Gate (What to Admit vs. Reject)

Evaluate every candidate signal from `### New Activity` against one core test: **Would a fresh agent opening the repository or workspace fail to know this without being told?**

### Admit (Durable, Non-Obvious Knowledge)
1. **User Preferences & Personal Identity (`memories/preferences.md`)**: Communication preferences, recurring workflow expectations, legal/billing identity, curation rubrics, and interaction habits not already covered by `AGENTS.md`.
2. **People & Collaborators (`memories/<person>.md`)**: Relationships, preferred names/pronunciation, contact/email routing, device preferences, and recurring family/collaborator context.
3. **Life Domains & Infrastructure (`memories/<domain>.md`)**: Smart home entity mappings, physical hardware quirks (e.g., Z-Wave node IDs, power/wattage profiles, relay hold times), LAN/Proxmox topology, financial routing, and recurring operational procedures.
4. **Environment Realities (`memories/guardrails.md`)**: OS/shell gotchas, network/IPv6 quirks, tool limitations, and third-party service failure modes.
5. **Cross-Session Project Context (`memories/<project>.md`)**: External accounts/domains/campaigns, cross-repo contracts, data locations outside the repo, and *why* a non-obvious design was chosen or *why* an attempted approach failed.

### Reject (Code-Evident or Ephemeral Noise)
1. **Code-Evident Details**: Keyboard shortcut tables, CSS hex palettes, UI layout coordinates, function signatures, file trees, or routine feature changelogs that an agent can read directly from the source code or `git log`.
2. **Transient Session Noise**: One-night overrides or snoozes, in-flight debugging steps, temporary IP workarounds, or one-off task checklists.
3. **Global Constitution Duplicates**: Rules already stated in `~/.gemini/config/AGENTS.md`.

*Semantic Judgment Note*: Judge durability by intent rather than surface phrasing. Casual phrasing like *"we switched to X for now"* often states a lasting decision, whereas *"snooze bedtime to 12:30 AM tonight"* is a single-evening action to discard.

---

## 2. Memory File Structure & Bullet Format

Keep memory files scannable and compact (target `< 250` lines, ceiling `500` lines per file). Organize entries under topical `## Section` headings as standalone 1–3 sentence bullets (`~20–60` words each):

```markdown
# <Domain, Person, or Project Title>
- **Workspace**: `file:///...` *(optional, for engineering projects)*
- **Runbook Skill**: `...` *(optional, if paired with a skill)*

## <Topical Section>
- **<Concise Topic>**: <Clear statement of the fact, decision, or routing rule, including brief causal rationale when non-obvious.> (YYYY-MM-DD)
```

### Formatting Guidelines
- **Atomic Bullets**: Put one distinct topic per bullet so future edits update a single line cleanly rather than rewriting a 300-word paragraph.
- **Literal Date Suffix**: Anchor `(YYYY-MM-DD)` to the literal `created_at` turn timestamp in `### New Activity` where the fact was stated or confirmed, rather than the consolidation run date.
- **Selective Warnings**: Add a `"Do not..."` sentence only when guarding against a genuine trap or hardware/service hazard. Omit artificial negative constraints on ordinary facts.
- **No HTML Comment Ceremony**: Write plain Markdown bullets without `<!-- INVARIANT_KEY -->` tags or multi-field `Target / Invariant / Negative Constraint / Rationale` blocks.

---

## 3. Procedural Workflow

```text
[0. Pre-Run Git Sync] ──> git pull --rebase --autostash --recurse-submodules origin main
         │
[1. Query Root Sessions] ──> Read-only SQLite (nesting_depth == 0, > watermark)
         │
[2. Extract New Activity] ──> Partitioned turns via skills/dreaming/scripts/dream_helpers.py
         │
[3. Load Active Context] ──> Read AGENTS.md, dreaming/index.md, and touched memories/*.md
         │
[4. Repo-Blindness Filter] ──> Distill atomic topical bullets; route secrets to credentials/
         │
[5. In-Place Update & Domain Hygiene] ──> Edit/add bullets; register new domains; prune empty stubs
         │
[6. Commit, Watermark & Push] ──> Commit dreaming/ Markdown only; save .state.json; push origin main
         │
[7. Weekly Deep Dream (If Due)] ──> Sequential pro subagent audit, deduplication, and pruning
```

### Step 0: Pre-Run Git Synchronization
Pull peer updates before reading or editing memory files so dual-node commits merge cleanly:
```bash
git -C ~/.gemini/config pull --rebase --autostash --recurse-submodules origin main || true
```

### Step 1: Query Recent Root Sessions
Use `skills/dreaming/scripts/dream_helpers.py` (`resolve_app_data_dir()` auto-detects `~/.gemini/antigravity` on Desktop IDE and `~/.gemini/antigravity-cli` on Headless CLI):
1. Load `dreaming/.state.json` via `load_state()`.
2. Call `query_root_sessions(since=state.last_consolidated_timestamp, exclude_running=True, min_step_count=1)` to fetch idle root sessions (`nesting_depth == 0`).
3. If zero sessions qualify, check `is_deep_dream_due(state)`: if `True`, jump to **Step 7**; otherwise exit quietly.

### Step 2: Stream Partitioned Transcripts
For each qualifying session, call `extract_compact_transcript(transcript_path, watermark=state.last_consolidated_timestamp, prior_context_turns=4)` and `render_partitioned_markdown()`:
- Distill new or updated facts strictly from `### New Activity` (`created_at > watermark`).
- Use `### Prior Context` (`<= 4` turns) only to resolve references and pronouns; do not re-extract or re-date untouched historical bullets.

### Step 3: Load Manifest, Active Memories, and Constitution
Read `~/.gemini/config/AGENTS.md`, `dreaming/index.md`, and the specific `dreaming/memories/<slug>.md` files relevant to the active sessions.

### Step 4: In-Place Contradiction Resolution & Domain Management
- **Git-Native Updates**: When a decision, entity ID, or preference changes, update or replace the existing bullet directly in place via `edit_file` so conflicting statements never coexist. Rely on `git log -p dreaming/` for history rather than writing to an archive file.
- **Anti-Fragmentation (`>= 60%` Overlap)**: Consolidate into an existing `memories/<slug>.md` file when topics overlap by 60% or more, appending new search terms to `Aliases` in `dreaming/index.md`.
- **Dynamic Minting & Stub Pruning**: For genuinely new people, domains, or projects, create `dreaming/memories/<slug>.md` and call `register_domain_in_manifest()`. Run `prune_empty_domains_from_manifest()` (`scan_memory_bullets()`) to remove any 0-bullet stub files.

### Step 5: Turbo Mode Auto-Commit & `AGENTS.md` Constitutional Gate
- **High-Confidence Updates (`>= 0.9`)**: In Turbo Mode (default), write durable bullets directly to `dreaming/memories/` and `dreaming/index.md`.
- **Ambiguous Candidates (`< 0.9`)**: Stage uncertain items to `dreaming/proposals/YYYY-MM-DD-<slug>.md` for review.
- **`AGENTS.md` Gate**: Keep `~/.gemini/config/AGENTS.md` human-reviewed. If transcript evidence suggests adding, refining, or retiring a global rule in `AGENTS.md`, stage a diff proposal in `dreaming/proposals/YYYY-MM-DD-agents-md.md` rather than editing `AGENTS.md` directly.
- **Stage Markdown Only**: Commit only files under `dreaming/` (never `dreaming/.state.json` or unrelated working-tree edits in `~/.gemini/config`):
  ```bash
  git -C ~/.gemini/config add dreaming/index.md dreaming/memories/ dreaming/proposals/
  git -C ~/.gemini/config commit -m "dream(<slug>): <concise summary of updated topics>"
  ```

### Step 6: Advance Host Watermark & Push to Peer Node
1. Persist `last_consolidated_timestamp`, `last_consolidated_session_id`, and `processed_session_ids` to local gitignored `dreaming/.state.json` via `update_state_watermark()`.
2. Rebase and push committed Markdown updates to GitHub:
   ```bash
   git -C ~/.gemini/config pull --rebase --autostash --recurse-submodules origin main
   git -C ~/.gemini/config push origin main
   ```

### Step 7: Weekly Deep Dream Audit (`Model="pro"`)
When `is_deep_dream_due(state)` returns `True` (`>= 7` days since `last_deep_dream_timestamp` and new sessions consolidated since then), invoke `invoke_subagent(TypeName="self", Model="pro", Role="Weekly Deep Dream Architect")` sequentially to audit `AGENTS.md`, `dreaming/index.md`, and all `dreaming/memories/*.md` files:
1. **Prune Repo-Redundant & Duplicate Bullets**: Remove bullets that duplicate `AGENTS.md` or merely restate code-evident UI/implementation details.
2. **Split & Tighten**: Break multi-topic paragraphs into crisp 1–3 sentence bullets and merge overlapping bullets within each file.
3. **Secret Sweep**: Verify no literal API keys, tokens, or government IDs leaked into `dreaming/memories/*.md`.
4. **Manifest Hygiene**: Enrich `dreaming/index.md` aliases and run `prune_empty_domains_from_manifest()`.
5. **Constitutional Proposals**: Stage high-leverage `AGENTS.md` promotions or demotions to `dreaming/proposals/YYYY-MM-DD-deep-dream.md`.
6. **Commit, Push & Record**: Commit `dreaming/` compactions (`dream(deep): weekly memory compaction and manifest hygiene`), push to `origin/main`, and call `record_deep_dream_completion()`.

---

## 4. Scheduled Runner Configuration

- **Windows Workstation (`sidecars/nightly-dreaming/sidecar.json`)**: Runs on cron `"0 3,13 * * *"` (`3:00 AM` plus `1:00 PM` daytime catch-up when the laptop slept overnight) using `--model=flash`.
- **Proxmox CT 102 (`antigravity-dreaming.timer` + `scripts/run_dream.sh`)**: Runs nightly at `03:00` (`Persistent=true`) against CT 102's local `~/.gemini/antigravity-cli/conversation_summaries.db`, pulling via `agy-core-sync.timer` and pushing `dreaming/` commits back to `origin/main`.
