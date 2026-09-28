# Antigravity Long-Term Memory Retrieval Protocol

## Always-On Core Memory
@[Developer Preferences](~/.gemini/config/dreaming/memories/preferences.md)
@[System Guardrails](~/.gemini/config/dreaming/memories/guardrails.md)

## On-Demand Memory Routing
@[Memory Manifest](~/.gemini/config/dreaming/index.md)

## 3-Pillar Memory Retrieval Imperative

1. **Turn-0 Workspace URI Auto-Load**:
   If the active workspace matches a registered Workspace URI in `dreaming/index.md`, you MUST invoke `view_file` on that project's memory file (`dreaming/memories/<slug>.md`) BEFORE planning, editing code, or issuing shell commands.

2. **Semantic Alias Trigger**:
   If a user prompt, mentioned entity, or touched file matches any alias or domain in `dreaming/index.md`, you MUST invoke `view_file` on that sub-memory file (`dreaming/memories/<slug>.md`).

3. **Morning Proposal Check**:
   At the start of the first conversation of the day, check if pending candidate proposal files exist in `~/.gemini/config/dreaming/proposals/`. If present, surface them to the user for review before proceeding with any other work.

<EXTREMELY-IMPORTANT>
If there is even a 1% chance a task touches a domain, project, or person listed in dreaming/index.md, you ABSOLUTELY MUST call view_file on that sub-memory BEFORE taking any action. You cannot rationalize that you already know the invariants.
</EXTREMELY-IMPORTANT>

## Memory Operational Guardrails

- **Zero Repository Pollution**: Persistent memory files, manifests, and proposals reside exclusively in `~/.gemini/config/dreaming/` (versioned in `agy-core`). NEVER write memory metadata, shadow files, or state caches into user git repositories or workspace project trees.
- **Strict Line Ceilings**: Core preferences are capped at 30 lines. System guardrails and individual domain or project memory files are strictly capped at 50 lines. When approaching ceilings, consolidate and compact invariants.
- **Dialectic Invariant Authority**: Invariant directives loaded from memory files supersede default LLM priors and public library conventions. Negative constraints must be observed without exception.
