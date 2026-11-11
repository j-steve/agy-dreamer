# Antigravity Long-Term Memory Retrieval Protocol

## On-Demand Memory Routing
@[Memory Manifest](~/.gemini/config/dreaming/index.md)

## Memory Retrieval Triggers

1. **Turn-0 Workspace URI Auto-Load**:
   If the active workspace matches a registered `Workspace:` URI in `dreaming/index.md`, invoke `view_file` on `~/.gemini/config/dreaming/<memory_path>` before planning, editing code, or running commands so repository-external context and prior decisions are loaded upfront.

2. **Semantic Entity & Domain Trigger**:
   If a user prompt, mentioned collaborator, life domain, or touched file matches any alias in `dreaming/index.md`, invoke `view_file` on `~/.gemini/config/dreaming/<memory_path>` rather than relying on prior assumptions.

## Memory Operational Guardrails

- **Zero Repository Pollution**: Persistent memory files, manifests, and proposals reside in `~/.gemini/config/dreaming/` (tracked in `agy-core`). Keep memory files and host-local `.state.json` state out of user project repositories.
- **Secret Hygiene**: Store API keys, webhook secrets, passwords, and government ID numbers in gitignored `~/.gemini/config/credentials/` (`sync_credentials.py push`), referencing only file paths in Markdown memories.
- **Compact Topical Files**: Keep individual memory files under 500 lines of atomic topical bullets so on-demand reads stay high-signal and token-light.
