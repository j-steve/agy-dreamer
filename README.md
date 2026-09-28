# agy-dreamer

> **Autonomous, long-term memory consolidation ("dreaming") engine for Google Antigravity.**  
> Distills ephemeral conversation transcripts into durable domain invariants and maintains an on-demand memory manifest.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Antigravity: Plugin](https://img.shields.io/badge/Antigravity-Plugin%20v2.0-purple.svg)](https://github.com/j-steve/agy-dreamer)
[![Python: 3.12+](https://img.shields.io/badge/Python-3.12+-green.svg)](https://www.python.org/)

---

## Overview

In long-running conversational programming systems, critical engineering decisions, tool quirks, and architectural invariants are frequently discussed, established, and then lost as conversation context scrolls away or sessions terminate.

`agy-dreamer` is an autonomous background consolidation engine for **Google Antigravity**. Inspired by biological sleep consolidation, it periodically wakes during idle periods, inspects session transcripts in `conversation_summaries.db`, extracts verified decisions and behavioral axioms, and records them into a version-controlled shadow memory store in your global Antigravity configuration (`~/.gemini/config/dreaming/`).

During runtime conversations, a lean, sub-2KB pointer manifest is injected into context, allowing the agent to dynamically inspect relevant domain invariants on demand via `view_file`—preventing context window bloat while eliminating model amnesia.

---

## Foundational Architectural Invariants

`agy-dreamer` operates under seven non-negotiable architectural invariants:

| # | Invariant | Description |
|---|-----------|-------------|
| **1** | **Dynamic Emergent Domaining** | Memory is **never** restricted to pre-configured software workspaces. The system autonomously discovers and mints categories across People, Infrastructure, Life Domains, Hardware, and Software Projects. |
| **2** | **Unconstrained Multi-Entity Scale** | **No artificial 20-file cap and no naive LRU eviction.** The manifest routing pattern effortlessly scales to 100+ distinct domain, person, and project files while consuming less than 10% of the active rules budget. |
| **3** | **Memory Manifest Pattern** | Global context is never polluted with full memory bodies. Only a lean pointer catalog (~80 bytes / ~20 tokens per entry) is declared in `index.md`. Detailed files are loaded strictly on demand via `view_file`. |
| **4** | **3-Pillar Runtime Retrieval Anchor** | Eliminates model amnesia through Turn-0 Workspace URI auto-loading, semantic alias triggers, morning proposal checks, and an explicit **1% Anti-Rationalization Imperative** blocking model excuses. |
| **5** | **Zero Repository Pollution** | Unattended background dreaming processes **never** write directly to user codebases or workspace git trees. All persistent memory lives safely in the user's configuration repo (`~/.gemini/config/dreaming/`). |
| **6** | **The Analyst Pattern** | Background processes run read-only analysis against historical logs. In Standard Mode, proposals are staged to `dreaming/proposals/YYYY-MM-DD.md` for human morning review before entering active memory. |
| **7** | **Pure Semantic Deduplication** | Repository hygiene is maintained by detecting concept overlap ($\ge 60\%$) and generating consolidation merge proposals, **never** by arbitrarily evicting legitimate files. |

---

## Memory Topology & Layout

All consolidated memory lives inside the user's global configuration (`~/.gemini/config/`):

```text
~/.gemini/config/
├── AGENTS.md                                # Root rules (loads Manifest & Retrieval Protocol)
├── config.json                              # Plugin enablement: "agy-dreamer": { "enabled": true }
├── plugins/
│   └── agy-dreamer/                         # The plugin engine
└── dreaming/                                # DEDICATED DREAMING SUBSYSTEM
    ├── .state.json                          # Watermark & state tracking
    ├── index.md                             # MASTER MANIFEST: Aliases, URIs & Routing (<2KB)
    ├── cold_start_catalog.md                # Cold-start discovery evidence & cluster catalog
    ├── memories/                            # FLAT DYNAMIC MEMORY STORE
    │   ├── preferences.md                   # Communication style, cognitive posture (Max 30 lines)
    │   ├── guardrails.md                    # Environment, tool, & OS realities (Max 50 lines)
    │   ├── developer-profile.md             # Self-persona, core heuristics, developer traits
    │   ├── collaborator.md                  # Collaborators, team members, domain contacts
    │   ├── devops-infrastructure.md         # Deployment, servers, containers, networks
    │   ├── sample-project-alpha.md          # Core architecture, data models, invariant boundaries
    │   └── service-dispatch.md              # Service orchestration & protocol contracts
    ├── proposals/                           # STAGING BUFFER FOR AMBIGUOUS CANDIDATES
    │   └── YYYY-MM-DD.md                    # Staged candidate diffs awaiting morning review
    └── archive/                             # DEPRECATED CONTEXT
        └── superseded.md                    # Historical record of superseded invariants
```

### The Master Manifest Schema (`dreaming/index.md`)

```markdown
# Antigravity Memory Manifest
Inspect specific sub-memories using `view_file` when conversation context matches.

### People & Collaborators (`dreaming/memories/`)
- `developer-profile.md`: [Developer, preferences, heuristics]
- `collaborator.md`: [Collaborator, team member, shared calendar]

### Life Domains & Infrastructure (`dreaming/memories/`)
- `devops-infrastructure.md`: [Docker, Kubernetes, CI/CD, cloud, server]

### Engineering Projects (`dreaming/memories/`)
- `sample-project-alpha.md`:
  - Workspace: `file:///path/to/sample-project-alpha`
  - Aliases: [Sample Project, alpha, perception, worker-pool]
- `service-dispatch.md`:
  - Workspace: `file:///path/to/service-dispatch`
  - Aliases: [Dispatch, service orchestration, protocol bus]
```

---

## 4-Tier Epistemic Classification

Every candidate signal extracted during dreaming passes through an epistemic classification matrix:

| Tier | Classification | Signal Criteria | Destination | Retention Policy |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1** | **User Interaction Axioms** | Explicit corrections on tone, depth, cognitive posture | `dreaming/memories/preferences.md` | Permanent; updated on direct conflict |
| **Tier 2** | **Project & Domain Invariants** | Architectural boundaries, non-negotiable data models | `dreaming/memories/<slug>.md` | Permanent; loaded on domain context |
| **Tier 3** | **Environment Realities** | Tool quirks, Python runtimes, OS paths, shell bugs | `dreaming/memories/guardrails.md` | Permanent; verified via system tools |
| **Tier 4** | **Transient Operational Noise** | Temporary debugging flags, time-bounded workarounds | **DISCARDED** | Evaluated via semantic LLM judgment |

> **Important:** Tier 4 filtering is a semantic judgment, not a naive keyword blacklist. Established practices that happen to use conversational language (*"I've been using mmap for now and it works great"*) are recognized as durable architectural invariants, whereas true temporary workarounds (*"skip test X today while server Y is down"*) are discarded.

### Keyed Invariant Standard

```markdown
<!-- INVARIANT_KEY: sample_project.data_integrity -->
<!-- LAST_CONFIRMED: 2026-09-27 (Session: 5b184a03) -->
- **Target**: `DataPipeline` stream modeling
  **Invariant**: Stream payloads must use typed schema validation.
  **Negative Constraint**: Unvalidated dictionary payloads and untyped blobs are strictly forbidden.
  **Rationale**: Downstream processors require strict type safety to prevent runtime crashes.
```

### Dialectic Supersession Engine

When a technical decision evolves or is contradicted:
1. The Dreamer matches the existing `<!-- INVARIANT_KEY: ... -->`.
2. It generates a dialectic supersession diff.
3. The obsolete invariant is moved to `dreaming/archive/superseded.md` marked `[SUPERSEDED]`, and the new rule is committed with an explicit `SUPERSEDES: <timestamp>` tag. Contradictory rules are never permitted to coexist.

---

## Plugin Component Architecture

The `agy-dreamer` plugin bundle is structured as follows:

```text
agy-dreamer/
├── plugin.json                     # Antigravity plugin manifest
├── README.md                       # Architectural documentation & usage guide
├── .gitignore                      # Python bytecode, pytest caches, OS artifacts
├── rules/
│   └── AGENTS.md                   # Runtime Retrieval Anchor & Anti-Rationalization rules
├── skills/
│   └── dreaming/
│       └── SKILL.md                # 4-Tier consolidation runbook, modes, and prompt
├── scripts/
│   ├── dream_helpers.py            # Deterministic SQLite queries, transcript parsing, manifest ops
│   └── cold_start.py               # 3-Stage Map-Reduce Cold-Start CLI
└── tests/
    ├── conftest.py                 # Pytest fixtures and mock database generators
    ├── test_dream_helpers.py       # Unit tests for helper engine
    ├── test_cold_start.py          # Integration tests for cold-start bootstrapping
    └── test_plugin_compliance.py   # Manifest schema & rules budget tests
```

---

## Installation & 1-Click Setup

Setting up `agy-dreamer` is fully automated. You do **not** need to manually click through UI panels, create folders, or copy-paste prompts into modals.

---

### Step 1: Install the Plugin

Add `agy-dreamer` to your Antigravity plugins directory (`~/.gemini/config/plugins/`):

#### Option A: Clone Directly (Standard Installation)
```powershell
git clone https://github.com/j-steve/agy-dreamer.git "$env:USERPROFILE\.gemini\config\plugins\agy-dreamer"
```

#### Option B: Git Submodule (Recommended if version-controlling `agy-core`)
```powershell
Set-Location "$env:USERPROFILE\.gemini\config"
git submodule add https://github.com/j-steve/agy-dreamer.git plugins/agy-dreamer
git commit -m "feat(plugins): add agy-dreamer as submodule"
```

#### Option C: Development Symlink (For local development or contributions)
```powershell
New-Item -ItemType SymbolicLink -Path "$env:USERPROFILE\.gemini\config\plugins\agy-dreamer" -Target "C:\Users\<username>\Documents\My Code\agy-dreamer"
```

---

### Step 2: Run the 1-Click Setup Script

Run the automated setup script from the plugin directory:

```powershell
cd "$env:USERPROFILE\.gemini\config\plugins\agy-dreamer"
py -3 scripts/setup_dreamer.py
```

> [!TIP]
> **Immediate Bootstrapping:** To backfill and synthesize baseline memories from your historical sessions right away, add the `--bootstrap` flag:
> ```powershell
> py -3 scripts/setup_dreamer.py --bootstrap
> ```

#### What the script does automatically in < 1 second:
1. **Enables the Plugin**: Registers `"agy-dreamer": { "enabled": true }` in `~/.gemini/config/config.json`.
2. **Scaffolds Directories**: Creates `~/.gemini/config/dreaming/{memories,proposals,archive}` and initializes `.state.json`.
3. **Registers the Workspace Project**: Registers the dedicated `dreaming` workspace in `~/.gemini/config/projects/`.
4. **Configures the Scheduled Sidecar Task**: Writes `~/.gemini/config/sidecars/nightly-dreaming/sidecar.json` with the hardened prompt and schedules it in `config.json` (`Schedule: 0 3 * * *`).

Antigravity's scheduler daemon hot-reloads the changes immediately. You are ready to go!

---

### Step 3: Runtime Retrieval in Action (Zero Extra Effort)

Once configured, memory consolidation and retrieval are completely autonomous:
1. **Nightly Consolidation**: The background scheduler wakes at 3:00 AM, parses recent root session transcripts, extracts Tier 1–3 invariants, and auto-commits them in Turbo Mode.
2. **Turn-0 Workspace URI Auto-Load**: Opening a known workspace (e.g. `sample-project-alpha`) instantly loads its invariant file into context before the first message.
3. **Semantic Alias Triggers**: Mentioning a domain keyword, person, or tool triggers an on-demand `view_file` on the corresponding sub-memory.
4. **Morning Review**: If any borderline candidates were staged, the morning agent alerts you with a 10-second review card.

<details>
<summary><b>Advanced: Custom Cron Schedules & Manual Configuration</b></summary>

#### Customizing the Cron Schedule
You can pass a custom cron expression to the setup script:
```powershell
py -3 scripts/setup_dreamer.py --cron "0 4 * * *"
```

#### Manual Scheduled Task UI Configuration (Alternative)
If you prefer configuring via the Antigravity desktop UI:
1. Open folder `~/.gemini/config/dreaming` in Antigravity.
2. Go to **Scheduled Tasks** -> **+ New Scheduled Task**.
3. Select `dreaming` project, Cron: `0 3 * * *`, and prompt:
   ```text
   Execute the dreaming skill to consolidate memories into agy-core:
   1. Check if cold-start is needed in dreaming/.state.json; if so, bootstrap baseline memories.
   2. Otherwise, scan root sessions modified since the watermark timestamp.
   3. Extract invariants using the 4-tier epistemic rubric and auto-commit in Turbo Mode (>= 0.9 confidence).
   4. Display a clean morning summary card in chat of all changes made. If no new sessions exist, report "No new sessions to consolidate" and finish.
   ```
</details>

---

## Operational Configuration & Execution Modes

Configure mode preference in `~/.gemini/config/dreaming/.state.json`:

| Aspect | Standard Mode | Turbo Mode (Default) |
| :--- | :--- | :--- |
| **Destination** | Staged in `dreaming/proposals/YYYY-MM-DD.md` | Auto-committed to active memory files |
| **Human Review** | Mandatory morning review card | Optional morning summary notification |
| **Confidence Gate**| N/A (Human decides) | High confidence ($\ge 0.9$) auto-committed; ambiguous items staged |
| **Rollback** | Discard proposal before commit | 1-command rollback via `git revert HEAD` |

---

## Cold-Start Historical Ingestion

When first installed, `agy-dreamer` automatically bootstraps its knowledge store by analyzing your historical root conversations in `conversation_summaries.db` through a 3-Stage Map-Reduce pipeline:

1. **Stage 1 (Deterministic Map):** Filters sessions with `nesting_depth == 0`. Resolves sessions anchored to known project workspace URIs.
2. **Stage 2 (Token-Capped Distillation):** Streams JSONL transcripts for unanchored sessions, stripping tool outputs and extracting structured entity-topic tuples.
3. **Stage 3 (Graph Clustering & Reduce):** Performs semantic co-occurrence clustering to discover emergent categories, mints baseline memory files in `dreaming/memories/<slug>.md`, and writes the initial `dreaming/index.md` manifest.

---

## Development & Testing

Run the test suite using `pytest`:

```powershell
# Run all unit tests
pytest -v tests/

# Run plugin compliance verification
pytest -v tests/test_plugin_compliance.py
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
