# Copyright 2026 Google Antigravity Plugin agy-dreamer Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Autonomous Cold-Start Bootstrapping Engine for agy-dreamer (Milestone 3).

Executes the deterministic 3-stage Map-Reduce cold-start pipeline:
- Stage 1 (Fast Metadata Map): Segregates anchored workspace sessions from unanchored sessions.
- Stage 2 (Transcript Distillation): Extracts compact transcripts and detects entities/topics.
- Stage 3 (Graph Clustering & Namespace Gating): Clusters knowledge into people/, domains/,
  and projects/ namespaces and generates the Master Manifest (memory/index.md).
- Catalog Generator: Emits memory/cold_start_catalog.md with evidence links.
- Bootstrapping Controller: Manages initialization, baseline memory files, and state persistence.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.dream_helpers import (
    DEFAULT_BRAIN_DIR,
    DEFAULT_DB_PATH,
    DEFAULT_STATE_FILE,
    DreamState,
    SessionSummary,
    extract_compact_transcript,
    extract_project_slug,
    load_state,
    parse_workspace_uris,
    query_root_sessions,
    save_state_atomic,
    uri_to_local_path,
)

__all__ = [
    "DreamState",
    "SessionSummary",
    "bootstrap_cold_start",
    "extract_compact_transcript",
    "extract_project_slug",
    "generate_cold_start_catalog",
    "load_state",
    "main",
    "parse_workspace_uris",
    "query_root_sessions",
    "run_stage1_fast_map",
    "run_stage2_distill",
    "run_stage3_cluster",
    "save_state_atomic",
    "uri_to_local_path",
]

# ============================================================================
# Top-Level Constants & Domain Knowledge Bases
# ============================================================================

logger = logging.getLogger(__name__)


# ============================================================================
# Public CLI Entrypoint
# ============================================================================


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for autonomous cold-start bootstrapping engine.

    Parses command-line arguments and dispatches execution to bootstrap_cold_start.

    Args:
        argv: Optional command-line argument list (defaults to sys.argv[1:]).

    Returns:
        Exit code: 0 on success, non-zero on failure.
    """
    args = _parse_cli_arguments(argv)
    _configure_logging(verbose=args.verbose)

    try:
        result = bootstrap_cold_start(
            db_path=args.db_path,
            brain_dir=args.brain_dir,
            output_memory_dir=args.output_dir,
            dry_run=args.dry_run,
            force=args.force,
            exclude_running=args.exclude_running,
            min_step_count=args.min_step_count,
        )
        _print_execution_summary(result)
        return 0
    except Exception as exc:
        logger.exception("Cold-start bootstrapping failed")
        print(f"Error: Cold-start bootstrapping failed: {exc}", file=sys.stderr)
        return 1


def _parse_cli_arguments(argv: list[str] | None) -> argparse.Namespace:
    """Configures and parses command-line arguments for cold-start CLI."""
    parser = argparse.ArgumentParser(
        description="Autonomous Cold-Start Bootstrapping Engine for agy-dreamer."
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=str(DEFAULT_DB_PATH),
        help="Path to conversation_summaries.db SQLite database",
    )
    parser.add_argument(
        "--brain-dir",
        type=str,
        default=str(DEFAULT_BRAIN_DIR),
        help="Path to root brain directory containing session logs",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_STATE_FILE.parent),
        help="Output directory for generated memory files and state",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate 3-stage Map-Reduce pipeline without writing to disk",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force execution even if cold-start is marked completed in state",
    )
    parser.add_argument(
        "--exclude-running",
        action="store_true",
        default=False,
        help="Exclude running sessions during cold-start (default: False)",
    )
    parser.add_argument(
        "--min-step-count",
        type=int,
        default=0,
        help="Minimum step count for session ingestion (default: 0)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose debug logging",
    )
    return parser.parse_args(argv)


def _configure_logging(verbose: bool) -> None:
    """Configures module and root logging levels based on verbose flag."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _print_execution_summary(result: dict[str, Any]) -> None:
    """Prints a structured human-readable execution summary to stdout."""
    status = result.get("status")
    print(f"\n{'=' * 60}")
    print(f"  Antigravity Cold-Start Bootstrapping Engine: {status.upper()}")
    print(f"{'=' * 60}")

    if status == "skipped":
        print(f"Reason: {result.get('reason')}")
        print("Cold-start already completed. Use --force to re-bootstrap.")
        return

    print(f"Total root sessions analyzed: {result.get('total_sessions', 0)}")
    print(f"Anchored sessions:           {result.get('anchored_sessions_count', 0)}")
    print(f"Unanchored sessions:         {result.get('unanchored_sessions_count', 0)}")

    clusters = result.get("clusters_count", {})
    print(f"People clusters:             {clusters.get('people', 0)}")
    print(f"Domain clusters:             {clusters.get('domains', 0)}")
    print(f"Project clusters:            {clusters.get('projects', 0)}")

    if result.get("dry_run"):
        print("\n[DRY-RUN MODE] No files were written to disk.")
        print(f"Candidate files:             {len(result.get('created_files', []))}")
    else:
        print(f"\nManifest path:               {result.get('manifest_path')}")
        print(f"State file path:             {result.get('state_path')}")
        print(f"Created files count:         {len(result.get('created_files', []))}")
    print(f"{'=' * 60}\n")


# ============================================================================
# High-Level Bootstrapping Controller
# ============================================================================


def bootstrap_cold_start(
    db_path: Path | str = DEFAULT_DB_PATH,
    brain_dir: Path | str = DEFAULT_BRAIN_DIR,
    output_memory_dir: Path | str = DEFAULT_STATE_FILE.parent,
    dry_run: bool = False,
    force: bool = False,
    exclude_running: bool = False,
    min_step_count: int = 0,
) -> dict[str, Any]:
    """Coordinates the full 3-Stage Map-Reduce Cold-Start Bootstrapping workflow.

    Evaluates memory/.state.json to prevent redundant execution unless force=True.
    Queries root sessions, partitions sessions via Stage 1, distills unanchored
    sessions via Stage 2, clusters taxonomy via Stage 3, and writes baseline
    manifests, catalogs, and state records.

    Args:
        db_path: Path to conversation_summaries.db.
        brain_dir: Path to root brain directory containing session logs.
        output_memory_dir: Target directory for memory files and state persistence.
        dry_run: When True, simulates pipeline and generates catalog without disk writes.
        force: When True, bypasses cold_start_completed check in .state.json.
        exclude_running: When True, filters out active CASCADE_RUN_STATUS_RUNNING sessions.
        min_step_count: Minimum step count required (default 0 for full cold-start).

    Returns:
        Summary dictionary containing execution metrics, file paths, and cluster counts.
    """
    db_file = Path(db_path)
    if str(db_path) != ":memory:" and not db_file.is_file():
        raise FileNotFoundError(f"Database file not found: {db_file}")

    mem_dir = Path(output_memory_dir)
    state_file = mem_dir / ".state.json"
    state = load_state(state_file)

    if state.cold_start_completed and not force:
        logger.info("Cold-start already completed in %s. Skipping.", state_file)
        return {
            "status": "skipped",
            "reason": "already_completed",
            "cold_start_completed": True,
            "state_file": str(state_file),
        }

    sessions = query_root_sessions(
        db_path=db_path,
        exclude_running=exclude_running,
        min_step_count=min_step_count,
    )
    if not sessions:
        logger.warning("No root sessions discovered in database %s", db_path)
        return {
            "status": "completed",
            "reason": "no_root_sessions",
            "total_sessions": 0,
            "anchored_sessions_count": 0,
            "unanchored_sessions_count": 0,
            "created_files": [],
        }

    anchored_map, unanchored_sessions = run_stage1_fast_map(sessions=sessions)
    distilled_items = run_stage2_distill(
        unanchored_sessions=unanchored_sessions,
        brain_dir=brain_dir,
    )
    clusters, manifest_content = run_stage3_cluster(
        anchored_map=anchored_map,
        distilled_items=distilled_items,
    )
    catalog_content = generate_cold_start_catalog(
        clusters=clusters,
        manifest_content=manifest_content,
    )

    created_files = _plan_memory_files(clusters=clusters)
    latest_ts = _find_latest_session_timestamp(sessions=sessions)

    if not dry_run:
        _write_all_cold_start_files(
            output_dir=mem_dir,
            clusters=clusters,
            manifest_content=manifest_content,
            catalog_content=catalog_content,
        )
        _persist_cold_start_state(
            state_file=state_file,
            sessions=sessions,
            latest_ts=latest_ts,
        )

    return {
        "status": "dry_run_completed" if dry_run else "completed",
        "dry_run": dry_run,
        "total_sessions": len(sessions),
        "anchored_sessions_count": sum(len(items) for items in anchored_map.values()),
        "unanchored_sessions_count": len(unanchored_sessions),
        "clusters_count": {
            "people": len(clusters.get("people", {})),
            "domains": len(clusters.get("domains", {})),
            "projects": len(clusters.get("projects", {})),
        },
        "created_files": created_files,
        "manifest_path": str(mem_dir / "index.md"),
        "state_path": str(state_file),
        "latest_session_timestamp": latest_ts,
        "catalog_content": catalog_content,
    }


def _find_latest_session_timestamp(sessions: list[SessionSummary]) -> str:
    """Finds the maximum ISO timestamp among processed root sessions."""
    if not sessions:
        return datetime.now(timezone.utc).isoformat()
    max_dt = max(s.last_modified_time for s in sessions)
    return max_dt.isoformat()


def _persist_cold_start_state(
    state_file: Path,
    sessions: list[SessionSummary],
    latest_ts: str,
) -> None:
    """Updates and saves DreamState after successful non-dry-run cold-start."""
    state = load_state(state_file)
    state.cold_start_completed = True
    state.cold_start_timestamp = datetime.now(timezone.utc).isoformat()
    state.last_consolidated_timestamp = ""
    state.watermark_last_modified_time = None
    state.processed_session_ids = []
    state.stats["total_root_sessions_scanned"] = len(sessions)
    save_state_atomic(state=state, state_file=state_file)


# ============================================================================
# Stage 1: Fast Metadata Extraction (Deterministic Map)
# ============================================================================


def run_stage1_fast_map(
    sessions: list[SessionSummary],
) -> tuple[dict[str, list[SessionSummary]], list[SessionSummary]]:
    """Separates sessions into anchored_by_repo and unanchored_sessions.

    Fast-track mapping that checks session workspace_uris against known repositories
    and local filesystem projects. Sessions with verified workspace URIs are
    bucketed directly into repository clusters; sessions with empty or unmapped
    workspace URIs are segregated for Stage 2 distillation.

    Args:
        sessions: List of SessionSummary records from SQLite query.

    Returns:
        A tuple of (anchored_map, unanchored_sessions) where anchored_map is a
        dict mapping project slugs to lists of SessionSummary objects.
    """
    anchored_map: dict[str, list[SessionSummary]] = {}
    unanchored_sessions: list[SessionSummary] = []

    for session in sessions:
        slug = _resolve_session_project_slug(session.workspace_uris)
        if slug:
            anchored_map.setdefault(slug, []).append(session)
        else:
            unanchored_sessions.append(session)

    return anchored_map, unanchored_sessions


def _resolve_session_project_slug(workspace_uris: list[str]) -> str | None:
    """Resolves a project slug from a list of session workspace URIs."""
    if not workspace_uris:
        return None

    for uri in workspace_uris:
        raw_slug = extract_project_slug(uri)
        if not raw_slug:
            continue
        normalized = _normalize_slug(raw_slug)
        if normalized:
            return normalized
    return None


def _normalize_slug(raw: str) -> str:
    """Normalizes arbitrary text or folder names into a clean kebab-case slug."""
    clean = raw.strip().lower()
    clean = re.sub(r"[\s_]+", "-", clean)
    clean = re.sub(r"[^a-z0-9\-]", "", clean)
    return clean.strip("-")


# ============================================================================
# Stage 2: Transcript Distillation (Token-Capped Map)
# ============================================================================


def run_stage2_distill(
    unanchored_sessions: list[SessionSummary],
    brain_dir: Path | str = DEFAULT_BRAIN_DIR,
) -> list[dict[str, Any]]:
    """Extracts compact transcripts and detects entities/topics for unanchored sessions.

    Streams transcript logs (skipping raw tool payloads), merges user requests,
    agent thoughts, and planner goals, and applies semantic keyword heuristics to
    classify domain concepts, technologies, and candidate namespaces.

    Args:
        unanchored_sessions: Sessions without explicit workspace URI anchors.
        brain_dir: Path to root brain directory containing session logs.

    Returns:
        List of distillation dictionaries containing extracted entities, topics,
        system components, suggested namespaces, and confidence scores.
    """
    distilled_items: list[dict[str, Any]] = []

    for session in unanchored_sessions:
        item = _distill_single_session(session=session, brain_dir=brain_dir)
        distilled_items.append(item)

    return distilled_items


def _distill_single_session(
    session: SessionSummary,
    brain_dir: Path | str,
) -> dict[str, Any]:
    """Distills a single unanchored session using compact transcript and metadata."""
    transcript = extract_compact_transcript(
        session_id=session.conversation_id,
        brain_dir=brain_dir,
    )
    corpus = _build_session_corpus(session=session, transcript=transcript)
    entities = _detect_entities_in_corpus(corpus)
    topics = _detect_topics_in_corpus(corpus)
    components = _detect_components_in_corpus(corpus)
    namespace, primary_slug = _infer_namespace_and_slug(
        topics=topics,
        entities=entities,
        corpus=corpus,
    )

    return {
        "conversation_id": session.conversation_id,
        "title": session.title,
        "preview": session.preview,
        "step_count": session.step_count,
        "last_modified_time": session.last_modified_time.isoformat(),
        "entities": sorted(entities),
        "topics": sorted(topics),
        "system_components": sorted(components),
        "suggested_namespace": namespace,
        "suggested_slug": primary_slug,
        "confidence": 0.95 if namespace != "domains" or primary_slug else 0.70,
        "has_transcript": bool(transcript.user_prompts or transcript.agent_thoughts),
    }


def _build_session_corpus(session: SessionSummary, transcript: Any) -> str:
    """Concatenates title, preview, prompts, and thoughts into a searchable text corpus."""
    parts = [session.title, session.preview]
    parts.extend(transcript.user_prompts)
    parts.extend(transcript.agent_thoughts)
    parts.extend(transcript.planner_goals)
    for tool in transcript.tool_summaries:
        parts.append(tool.get("summary", ""))
        parts.append(tool.get("action", ""))
        parts.append(tool.get("target", ""))
    return " ".join(parts)


def _detect_entities_in_corpus(corpus: str) -> set[str]:
    """Detects technical named entities present in the session text corpus."""
    entities: set[str] = set()
    matches = re.findall(r"\b[A-Z][a-zA-Z0-9_\-\.]{2,}\b", corpus)
    common_stops = {
        "the",
        "this",
        "that",
        "what",
        "when",
        "where",
        "how",
        "why",
        "there",
        "here",
        "with",
        "from",
        "into",
        "about",
        "after",
        "before",
        "could",
        "would",
        "should",
        "please",
        "check",
        "user",
        "agent",
        "true",
        "false",
        "none",
        "error",
        "test",
        "file",
        "code",
    }
    for m in matches:
        if m.lower() not in common_stops and len(m) > 3:
            entities.add(m)
    return entities


def _detect_topics_in_corpus(corpus: str) -> set[str]:
    """Detects broad technical categories from common software engineering patterns."""
    topics: set[str] = set()
    corpus_lower = corpus.lower()
    category_patterns = {
        "web-development": [
            "frontend",
            "backend",
            "react",
            "html",
            "css",
            "api",
            "rest",
            "graphql",
            "http",
        ],
        "data-engineering": [
            "sql",
            "database",
            "postgres",
            "sqlite",
            "query",
            "dataset",
            "dataframe",
            "etl",
        ],
        "devops-infrastructure": [
            "docker",
            "kubernetes",
            "ci/cd",
            "pipeline",
            "deploy",
            "server",
            "linux",
            "cloud",
        ],
        "machine-learning": [
            "model",
            "training",
            "inference",
            "dataset",
            "weights",
            "neural",
            "embedding",
            "llm",
        ],
        "system-automation": [
            "powershell",
            "bash",
            "cron",
            "script",
            "automation",
            "scheduled",
            "daemon",
        ],
    }
    for category, keywords in category_patterns.items():
        if any(kw in corpus_lower for kw in keywords):
            topics.add(category)
    return topics


def _detect_components_in_corpus(corpus: str) -> set[str]:
    """Detects software components or modules referenced in the corpus."""
    components: set[str] = set()
    matches = re.findall(
        r"\b[A-Z][a-zA-Z0-9]+(?:Service|Controller|Manager|Engine|Client|Pipeline|Router|Handler)\b",
        corpus,
    )
    for m in matches:
        components.add(m)
    return components


def _infer_namespace_and_slug(
    topics: set[str],
    entities: set[str],
    corpus: str,
) -> tuple[str, str]:
    """Infers target namespace (domains, projects) and primary slug generically."""
    for topic in sorted(topics):
        return "domains", topic
    return "domains", "general"


# ============================================================================
# Stage 3: Graph Clustering & Namespace Gating (Reduce)
# ============================================================================


def run_stage3_cluster(
    anchored_map: dict[str, list[SessionSummary]],
    distilled_items: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], str]:
    """Clusters sessions into people/, domains/, and projects/ namespaces.

    Synthesizes anchored project repositories with unanchored domain/entity items.
    Applies namespace gating rules and outputs the structured cluster taxonomy
    along with the strictly formatted Master Manifest string (memory/index.md).

    Args:
        anchored_map: Map of project slugs to SessionSummary lists from Stage 1.
        distilled_items: Distillation candidate records from Stage 2.

    Returns:
        A tuple of (clusters_dict, manifest_content_str) containing the categorized
        entities and the formatted memory/index.md content.
    """
    clusters: dict[str, dict[str, Any]] = {
        "people": _cluster_people(distilled_items=distilled_items),
        "domains": _cluster_domains(distilled_items=distilled_items),
        "projects": _cluster_projects(
            anchored_map=anchored_map,
            distilled_items=distilled_items,
        ),
    }

    manifest_content = _render_manifest_markdown(clusters=clusters)
    return clusters, manifest_content


def _cluster_people(distilled_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Generates people/ namespace clusters dynamically from discovered collaborators."""
    people: dict[str, Any] = {}
    for item in distilled_items:
        if item.get("suggested_namespace") == "people":
            slug = item.get("suggested_slug", "collaborator")
            if slug not in people:
                people[slug] = {
                    "slug": slug,
                    "file": f"{slug}.md",
                    "name": slug.replace("-", " ").title(),
                    "title": slug.replace("-", " ").title(),
                    "aliases": [slug.replace("-", " ").title(), slug],
                    "session_ids": [item["conversation_id"]],
                    "description": "Collaborator or Team Member",
                }
            elif item["conversation_id"] not in people[slug]["session_ids"]:
                people[slug]["session_ids"].append(item["conversation_id"])
    return people


def _cluster_domains(distilled_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Generates domains/ namespace clusters dynamically from discovered domain topics."""
    domains: dict[str, Any] = {}
    for item in distilled_items:
        if item.get("suggested_namespace") == "domains":
            slug = item.get("suggested_slug", "general")
            if slug not in domains:
                domains[slug] = {
                    "slug": slug,
                    "file": f"{slug}.md",
                    "title": slug.replace("-", " ").title(),
                    "aliases": [slug.replace("-", " ").title(), slug],
                    "session_ids": [item["conversation_id"]],
                }
            elif item["conversation_id"] not in domains[slug]["session_ids"]:
                domains[slug]["session_ids"].append(item["conversation_id"])
    return domains


def _cluster_projects(
    anchored_map: dict[str, list[SessionSummary]],
    distilled_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generates projects/ namespace clusters dynamically from anchored workspace sessions."""
    projects: dict[str, Any] = {}
    for slug, sessions in anchored_map.items():
        workspace_uri = _extract_best_workspace_uri(slug=slug, sessions=sessions)
        session_ids = [s.conversation_id for s in sessions]

        for item in distilled_items:
            if (
                item.get("suggested_slug") == slug
                and item["conversation_id"] not in session_ids
            ):
                session_ids.append(item["conversation_id"])

        projects[slug] = {
            "slug": slug,
            "file": f"{slug}.md",
            "title": slug.replace("-", " ").title(),
            "workspace_uri": workspace_uri,
            "aliases": [slug.replace("-", " ").title(), slug],
            "session_ids": session_ids,
        }

    return projects


def _extract_best_workspace_uri(slug: str, sessions: list[SessionSummary]) -> str:
    """Determines canonical workspace URI from sessions."""
    for session in sessions:
        if session.workspace_uris:
            return session.workspace_uris[0]
    return ""


def _render_manifest_markdown(clusters: dict[str, dict[str, Any]]) -> str:
    """Formats the Master Manifest (dreaming/index.md) strictly per blueprint specification."""
    lines: list[str] = [
        "# Antigravity Dreaming Manifest",
        "Inspect specific sub-memories in `memories/` using `view_file` when conversation context matches.",
        "",
        "### People & Collaborators (`memories/`)",
    ]

    for item in clusters.get("people", {}).values():
        aliases_str = ", ".join(item["aliases"])
        lines.append(f"- `memories/{item['file']}`: [{aliases_str}]")

    lines.extend(
        [
            "",
            "### Life Domains & Infrastructure (`memories/`)",
        ]
    )
    for item in clusters.get("domains", {}).values():
        aliases_str = ", ".join(item["aliases"])
        lines.append(f"- `memories/{item['file']}`: [{aliases_str}]")

    lines.extend(
        [
            "",
            "### Engineering Projects (`memories/`)",
        ]
    )
    for item in clusters.get("projects", {}).values():
        aliases_str = ", ".join(item["aliases"])
        lines.extend(
            [
                f"- `memories/{item['file']}`:",
                f"  - Workspace: `{item['workspace_uri']}`",
                f"  - Aliases: [{aliases_str}]",
            ]
        )

    return "\n".join(lines) + "\n"


# ============================================================================
# Memory Catalog Generator
# ============================================================================


def generate_cold_start_catalog(
    clusters: dict[str, dict[str, Any]],
    manifest_content: str,
) -> str:
    """Generates memory/cold_start_catalog.md documenting clusters and evidence.

    Args:
        clusters: Grouped taxonomy clusters across people, domains, and projects.
        manifest_content: Exact string content of the memory/index.md manifest.

    Returns:
        Structured markdown string for memory/cold_start_catalog.md.
    """
    total_people = len(clusters.get("people", {}))
    total_domains = len(clusters.get("domains", {}))
    total_projects = len(clusters.get("projects", {}))

    lines: list[str] = [
        "# Cold-Start Memory Catalog",
        "",
        "This catalog documents the baseline taxonomy discovered during autonomous",
        "cold-start bootstrapping. It links discovered memory files to supporting session evidence.",
        "",
        "## Summary Metrics",
        f"- **People & Collaborators**: {total_people}",
        f"- **Life Domains & Infrastructure**: {total_domains}",
        f"- **Engineering Projects**: {total_projects}",
        "",
        "## Discovered Clusters & Supporting Evidence",
        "",
        "### 1. People (`memories/`)",
    ]

    for item in clusters.get("people", {}).values():
        evidence_count = len(item.get("session_ids", []))
        title = item.get("name") or item.get("slug") or item.get("file", "")
        lines.extend(
            [
                f"#### `memories/{item['file']}` — {title}",
                f"- **Supporting Sessions**: {evidence_count} sessions",
                f"- **Aliases**: {', '.join(item.get('aliases', []))}",
                "",
            ]
        )

    lines.append("### 2. Domains (`memories/`)")
    for item in clusters.get("domains", {}).values():
        evidence_count = len(item.get("session_ids", []))
        title = item.get("title") or item.get("slug") or item.get("file", "")
        lines.extend(
            [
                f"#### `memories/{item['file']}` — {title}",
                f"- **Supporting Sessions**: {evidence_count} sessions",
                f"- **Aliases**: {', '.join(item.get('aliases', []))}",
                "",
            ]
        )

    lines.append("### 3. Engineering Projects (`memories/`)")
    for item in clusters.get("projects", {}).values():
        evidence_count = len(item.get("session_ids", []))
        title = item.get("title") or item.get("slug") or item.get("file", "")
        lines.extend(
            [
                f"#### `memories/{item['file']}` — {title}",
                f"- **Workspace URI**: `{item.get('workspace_uri', '')}`",
                f"- **Supporting Sessions**: {evidence_count} sessions",
                f"- **Aliases**: {', '.join(item.get('aliases', []))}",
                "",
            ]
        )

    lines.extend(
        [
            "## Master Manifest (`dreaming/index.md`)",
            "```markdown",
            manifest_content.strip(),
            "```",
            "",
        ]
    )

    return "\n".join(lines)


# ============================================================================
# Memory File Generation & Writing Helpers
# ============================================================================


def _plan_memory_files(clusters: dict[str, dict[str, Any]]) -> list[str]:
    """Calculates the list of relative file paths that will be generated."""
    files: list[str] = [
        "index.md",
        "cold_start_catalog.md",
        "memories/preferences.md",
        "memories/guardrails.md",
    ]
    for category in ("people", "domains", "projects"):
        for item in clusters.get(category, {}).values():
            files.append(f"memories/{item['file']}")
    return sorted(files)


def _write_all_cold_start_files(
    output_dir: Path,
    clusters: dict[str, dict[str, Any]],
    manifest_content: str,
    catalog_content: str,
) -> None:
    """Writes all baseline memory files and subdirectories to the target directory."""
    for sub in ("memories", "proposals", "archive"):
        (output_dir / sub).mkdir(parents=True, exist_ok=True)

    _write_text_file(output_dir / "index.md", manifest_content)
    _write_text_file(output_dir / "cold_start_catalog.md", catalog_content)
    _write_text_file(
        output_dir / "memories" / "preferences.md", _build_core_preferences_content()
    )
    _write_text_file(
        output_dir / "memories" / "guardrails.md", _build_core_guardrails_content()
    )

    for item in clusters.get("people", {}).values():
        content = _build_person_file_content(item)
        _write_text_file(output_dir / "memories" / item["file"], content)

    for item in clusters.get("domains", {}).values():
        content = _build_domain_file_content(item)
        _write_text_file(output_dir / "memories" / item["file"], content)

    for item in clusters.get("projects", {}).values():
        content = _build_project_file_content(item)
        _write_text_file(output_dir / "memories" / item["file"], content)


def _write_text_file(file_path: Path, content: str) -> None:
    """Writes text content to a file with UTF-8 encoding."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)


def _build_core_preferences_content() -> str:
    """Builds baseline content for memories/preferences.md (Tier 1 User Axioms)."""
    return (
        "# Developer Preferences & Axioms (Tier 1)\n\n"
        "<!-- Core developer preferences and interaction axioms distilled from session transcripts by the Dreamer agent -->\n"
    )


def _build_core_guardrails_content() -> str:
    """Builds baseline content for memories/guardrails.md (Tier 3 Host Environment Realities)."""
    return (
        "# Host Environment Guardrails (Tier 3)\n\n"
        "<!-- Critical environment guardrails and technical invariants distilled from session transcripts by the Dreamer agent -->\n"
    )


def _build_person_file_content(item: dict[str, Any]) -> str:
    """Builds content for people/<slug>.md files."""
    slug = item["slug"]
    name = item.get("name", slug.replace("-", " ").title())
    aliases = ", ".join(item.get("aliases", []))
    lines = [f"# Person: {name}", ""]
    lines.append(f"- **Role**: {item.get('description', 'Collaborator')}")
    if aliases:
        lines.append(f"- **Aliases**: {aliases}")
    lines.extend(
        [
            "",
            "<!-- Invariants are autonomously distilled from session transcripts by the Dreamer agent -->",
            "",
        ]
    )
    return "\n".join(lines)


def _build_domain_file_content(item: dict[str, Any]) -> str:
    """Builds clean initial starter header for domains/<slug>.md files."""
    slug = item["slug"]
    title = item.get("title", slug.replace("-", " ").title())
    aliases = ", ".join(item.get("aliases", []))
    lines = [f"# Domain: {title}", ""]
    if aliases:
        lines.append(f"- **Aliases**: {aliases}")
    lines.extend(
        [
            "",
            "<!-- Invariants are autonomously distilled from session transcripts by the Dreamer agent -->",
            "",
        ]
    )
    return "\n".join(lines)


def _build_project_file_content(item: dict[str, Any]) -> str:
    """Builds clean initial starter header for projects/<slug>.md files."""
    slug = item["slug"]
    title = item.get("title", slug.replace("-", " ").title())
    workspace_uri = item.get("workspace_uri", "")
    aliases = ", ".join(item.get("aliases", []))
    lines = [f"# Project: {title}", ""]
    if workspace_uri:
        lines.append(f"- **Workspace**: `{workspace_uri}`")
    if aliases:
        lines.append(f"- **Aliases**: {aliases}")
    lines.extend(
        [
            "",
            "<!-- Invariants are autonomously distilled from session transcripts by the Dreamer agent -->",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
