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

"""Comprehensive unit and integration test suite for scripts/cold_start.py (Milestone 3)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.cold_start import (
    bootstrap_cold_start,
    generate_cold_start_catalog,
    main,
    run_stage1_fast_map,
    run_stage2_distill,
    run_stage3_cluster,
)
from scripts.dream_helpers import (
    DEFAULT_BRAIN_DIR,
    DEFAULT_DB_PATH,
    SessionSummary,
    load_state,
)

# ============================================================================
# Helpers & Fixtures
# ============================================================================


def _create_session(
    conversation_id: str,
    title: str = "Test Session",
    preview: str = "Preview text",
    workspace_uris: list[str] | None = None,
    step_count: int = 10,
    last_modified_time: datetime | None = None,
) -> SessionSummary:
    """Helper factory for creating mock SessionSummary instances."""
    return SessionSummary(
        conversation_id=conversation_id,
        title=title,
        preview=preview,
        last_modified_time=last_modified_time
        or datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc),
        workspace_uris=workspace_uris or [],
        step_count=step_count,
        status="CASCADE_RUN_STATUS_IDLE",
        nesting_depth=0,
    )


# ============================================================================
# Stage 1 Unit Tests: Fast Metadata Map
# ============================================================================


def test_stage1_fast_map_nominal() -> None:
    """Verifies that Stage 1 cleanly partitions anchored and unanchored sessions."""
    sessions = [
        _create_session(
            "s1",
            "Service Beta Dispatch",
            workspace_uris=["file:///c%3A/Projects/service-beta"],
        ),
        _create_session(
            "s2",
            "Sample Alpha Pipeline",
            workspace_uris=["file:///c%3A/Projects/sample-alpha"],
        ),
        _create_session(
            "s3",
            "Analytics Worker",
            workspace_uris=["file:///c%3A/Projects/analytics-worker"],
        ),
        _create_session("s4", "DevOps Infrastructure Setup", workspace_uris=[]),
        _create_session("s5", "Data Pipeline Discussion", workspace_uris=[]),
    ]

    anchored_map, unanchored_sessions = run_stage1_fast_map(sessions)

    assert "service-beta" in anchored_map
    assert len(anchored_map["service-beta"]) == 1
    assert anchored_map["service-beta"][0].conversation_id == "s1"

    assert "sample-alpha" in anchored_map
    assert len(anchored_map["sample-alpha"]) == 1
    assert anchored_map["sample-alpha"][0].conversation_id == "s2"

    assert "analytics-worker" in anchored_map
    assert len(anchored_map["analytics-worker"]) == 1
    assert anchored_map["analytics-worker"][0].conversation_id == "s3"

    assert len(unanchored_sessions) == 2
    unanchored_ids = {s.conversation_id for s in unanchored_sessions}
    assert unanchored_ids == {"s4", "s5"}


def test_stage1_fast_map_empty() -> None:
    """Verifies that an empty session list returns empty partitions."""
    anchored_map, unanchored_sessions = run_stage1_fast_map([])
    assert anchored_map == {}
    assert unanchored_sessions == []


def test_stage1_fast_map_custom_workspace() -> None:
    """Verifies that dynamic custom projects are also properly anchored."""
    session = _create_session(
        "s_custom",
        "Custom Tooling",
        workspace_uris=["file:///c%3A/Projects/my-custom-engine"],
    )
    anchored_map, unanchored_sessions = run_stage1_fast_map([session])

    assert "my-custom-engine" in anchored_map
    assert len(anchored_map["my-custom-engine"]) == 1
    assert len(unanchored_sessions) == 0


def test_stage1_fast_map_malformed_uris() -> None:
    """Verifies that empty or unparseable URIs are treated as unanchored."""
    sessions = [
        _create_session("s_bad1", "Bad URI", workspace_uris=[""]),
        _create_session("s_bad2", "Bad URI 2", workspace_uris=["file:///"]),
    ]
    anchored_map, unanchored_sessions = run_stage1_fast_map(sessions)
    assert len(anchored_map) == 0
    assert len(unanchored_sessions) == 2


# ============================================================================
# Stage 2 Unit Tests: Transcript Distillation
# ============================================================================


def test_stage2_distill_devops_domain(tmp_path: Path) -> None:
    """Verifies detection of devops-infrastructure entities and topics from transcripts."""
    brain_dir = tmp_path / "brain"
    log_dir = brain_dir / "sess-devops" / ".system_generated" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "transcript.jsonl").write_text(
        json.dumps(
            {
                "type": "USER_INPUT",
                "content": "<USER_REQUEST>Deploy Docker containers to Kubernetes server</USER_REQUEST>",
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "PLANNER_RESPONSE",
                "thinking": "Check Docker daemon and Kubernetes cluster status.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    session = _create_session(
        "sess-devops", "Cluster Deployment", "Configuring Docker and Kubernetes"
    )
    distilled = run_stage2_distill([session], brain_dir=brain_dir)

    assert len(distilled) == 1
    item = distilled[0]
    assert item["conversation_id"] == "sess-devops"
    assert "Docker" in item["entities"]
    assert "Kubernetes" in item["entities"]
    assert "devops-infrastructure" in item["topics"]
    assert item["suggested_namespace"] == "domains"
    assert item["suggested_slug"] == "devops-infrastructure"


def test_stage2_distill_data_engineering_domain(tmp_path: Path) -> None:
    """Verifies detection of data-engineering domain signals."""
    brain_dir = tmp_path / "brain"
    log_dir = brain_dir / "sess-data" / ".system_generated" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "transcript.jsonl").write_text(
        json.dumps(
            {
                "type": "USER_INPUT",
                "content": (
                    "<USER_REQUEST>Build postgres database ETL pipeline and query dataset"
                    "</USER_REQUEST>"
                ),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    session = _create_session("sess-data", "ETL Pipeline", "Postgres dataset queries")
    distilled = run_stage2_distill([session], brain_dir=brain_dir)

    assert len(distilled) == 1
    item = distilled[0]
    assert "Postgres" in item["entities"]
    assert "data-engineering" in item["topics"]
    assert item["suggested_namespace"] == "domains"
    assert item["suggested_slug"] == "data-engineering"


def test_stage2_distill_web_development_domain(tmp_path: Path) -> None:
    """Verifies detection of web-development domain signals."""
    brain_dir = tmp_path / "brain"
    log_dir = brain_dir / "sess-web" / ".system_generated" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "transcript.jsonl").write_text(
        json.dumps(
            {
                "type": "USER_INPUT",
                "content": "<USER_REQUEST>Build react frontend components and rest api endpoints</USER_REQUEST>",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    session = _create_session("sess-web", "Web Development", "Frontend React UI")
    distilled = run_stage2_distill([session], brain_dir=brain_dir)

    assert len(distilled) == 1
    item = distilled[0]
    assert "web-development" in item["topics"]
    assert item["suggested_namespace"] == "domains"
    assert item["suggested_slug"] == "web-development"


def test_stage2_distill_missing_transcript(tmp_path: Path) -> None:
    """Verifies that missing transcripts are handled defensively without failure."""
    brain_dir = tmp_path / "brain"  # Empty directory
    session = _create_session(
        "sess-missing", "Missing Transcript Session", "Preview of deleted session"
    )

    distilled = run_stage2_distill([session], brain_dir=brain_dir)
    assert len(distilled) == 1
    assert distilled[0]["conversation_id"] == "sess-missing"
    assert distilled[0]["has_transcript"] is False


def test_stage2_distill_empty_list() -> None:
    """Verifies that an empty session list returns an empty distillation list."""
    assert run_stage2_distill([]) == []


# ============================================================================
# Stage 3 Unit Tests: Graph Clustering & Manifest Generation
# ============================================================================


def test_stage3_cluster_structure_and_manifest() -> None:
    """Verifies Stage 3 clustering across people, domains, and projects."""
    anchored_map = {
        "sample-project-alpha": [
            _create_session(
                "s_alpha",
                "Alpha Pipeline",
                workspace_uris=["file:///c%3A/Projects/sample-project-alpha"],
            )
        ],
        "service-beta": [
            _create_session(
                "s_beta",
                "Beta Router",
                workspace_uris=["file:///c%3A/Projects/service-beta"],
            )
        ],
    }

    distilled_items = [
        {
            "conversation_id": "s_devops",
            "title": "DevOps Setup",
            "entities": ["Docker", "Kubernetes"],
            "topics": ["devops-infrastructure"],
            "suggested_namespace": "domains",
            "suggested_slug": "devops-infrastructure",
        },
        {
            "conversation_id": "s_alice",
            "title": "Alice Tasks",
            "entities": ["Alice"],
            "topics": [],
            "suggested_namespace": "people",
            "suggested_slug": "alice",
        },
    ]

    clusters, manifest_content = run_stage3_cluster(
        anchored_map=anchored_map,
        distilled_items=distilled_items,
    )

    # Validate cluster categories
    assert "people" in clusters
    assert "domains" in clusters
    assert "projects" in clusters

    # Validate people
    assert "alice" in clusters["people"]
    assert "s_alice" in clusters["people"]["alice"]["session_ids"]

    # Validate domains
    assert "devops-infrastructure" in clusters["domains"]
    assert "s_devops" in clusters["domains"]["devops-infrastructure"]["session_ids"]

    # Validate projects
    assert "sample-project-alpha" in clusters["projects"]
    assert "service-beta" in clusters["projects"]
    assert "s_alpha" in clusters["projects"]["sample-project-alpha"]["session_ids"]
    assert "s_beta" in clusters["projects"]["service-beta"]["session_ids"]

    # Validate Manifest format
    assert manifest_content.startswith("# Antigravity Dreaming Manifest")
    assert "### People & Collaborators (`memories/`)" in manifest_content
    assert "- `memories/alice.md`: [Alice, alice]" in manifest_content
    assert "### Life Domains & Infrastructure (`memories/`)" in manifest_content
    assert (
        "- `memories/devops-infrastructure.md`: [Devops Infrastructure, devops-infrastructure]"
        in manifest_content
    )
    assert "### Engineering Projects (`memories/`)" in manifest_content
    assert "- `memories/sample-project-alpha.md`:" in manifest_content
    assert (
        "  - Workspace: `file:///c%3A/Projects/sample-project-alpha`"
        in manifest_content
    )
    assert "- `memories/service-beta.md`:" in manifest_content
    assert "  - Workspace: `file:///c%3A/Projects/service-beta`" in manifest_content


def test_generate_cold_start_catalog() -> None:
    """Verifies generation and content of memory/cold_start_catalog.md."""
    clusters = {
        "people": {
            "alice": {
                "file": "alice.md",
                "name": "Alice",
                "aliases": ["Alice", "developer"],
                "session_ids": ["s1", "s2"],
            }
        },
        "domains": {
            "devops-infrastructure": {
                "file": "devops-infrastructure.md",
                "title": "DevOps & Infrastructure",
                "aliases": ["Docker", "Kubernetes"],
                "session_ids": ["s3"],
            }
        },
        "projects": {
            "service-beta": {
                "file": "service-beta.md",
                "title": "Service Beta",
                "workspace_uri": "file:///c%3A/Projects/service-beta",
                "aliases": ["Service Beta", "router"],
                "session_ids": ["s4"],
            }
        },
    }
    manifest = "# Manifest preview"
    catalog = generate_cold_start_catalog(clusters=clusters, manifest_content=manifest)

    assert "# Cold-Start Memory Catalog" in catalog
    assert "- **People & Collaborators**: 1" in catalog
    assert "- **Life Domains & Infrastructure**: 1" in catalog
    assert "- **Engineering Projects**: 1" in catalog
    assert "#### `memories/alice.md` — Alice" in catalog
    assert "- **Supporting Sessions**: 2 sessions" in catalog
    assert (
        "#### `memories/devops-infrastructure.md` — DevOps & Infrastructure" in catalog
    )
    assert "#### `memories/service-beta.md` — Service Beta" in catalog
    assert manifest in catalog


# ============================================================================
# Bootstrapping Controller Integration Tests
# ============================================================================


def test_bootstrap_cold_start_full_pipeline(
    mock_db_path: Path,
    mock_brain_dir: Path,
    tmp_path: Path,
) -> None:
    """Tests the complete cold-start pipeline writing to a temporary directory."""
    output_mem_dir = tmp_path / "memory_output"

    result = bootstrap_cold_start(
        db_path=mock_db_path,
        brain_dir=mock_brain_dir,
        output_memory_dir=output_mem_dir,
        dry_run=False,
        force=False,
    )

    assert result["status"] == "completed"
    assert result["dry_run"] is False
    assert result["total_sessions"] > 0
    assert result["anchored_sessions_count"] > 0

    # Verify all expected files exist on disk
    expected_files = [
        output_mem_dir / "index.md",
        output_mem_dir / "cold_start_catalog.md",
        output_mem_dir / "memories" / "preferences.md",
        output_mem_dir / "memories" / "guardrails.md",
        output_mem_dir / "memories" / "service-dispatch.md",
        output_mem_dir / ".state.json",
    ]
    for file_path in expected_files:
        assert file_path.is_file(), f"Expected file not found: {file_path}"

    # Verify manifest content
    manifest_text = (output_mem_dir / "index.md").read_text(encoding="utf-8")
    assert "# Antigravity Dreaming Manifest" in manifest_text
    assert "service-dispatch.md" in manifest_text

    # Verify state file content
    state = load_state(output_mem_dir / ".state.json")
    assert state.cold_start_completed is True
    assert state.cold_start_timestamp is not None
    assert len(state.processed_session_ids) == 0
    assert state.stats["total_root_sessions_scanned"] > 0


def test_bootstrap_cold_start_dry_run(
    mock_db_path: Path,
    mock_brain_dir: Path,
    tmp_path: Path,
) -> None:
    """Verifies that dry-run mode simulates the pipeline without writing to disk."""
    output_mem_dir = tmp_path / "memory_dry_run"

    result = bootstrap_cold_start(
        db_path=mock_db_path,
        brain_dir=mock_brain_dir,
        output_memory_dir=output_mem_dir,
        dry_run=True,
        force=False,
    )

    assert result["status"] == "dry_run_completed"
    assert result["dry_run"] is True
    assert result["total_sessions"] > 0
    assert len(result["created_files"]) > 0
    assert result["catalog_content"] != ""

    # Verify nothing was written to disk
    assert not (output_mem_dir / "index.md").exists()
    assert not (output_mem_dir / ".state.json").exists()


def test_bootstrap_cold_start_idempotency_and_force(
    mock_db_path: Path,
    mock_brain_dir: Path,
    tmp_path: Path,
) -> None:
    """Verifies that subsequent runs without force skip, and force re-runs."""
    output_mem_dir = tmp_path / "memory_idempotency"

    # First run: writes files
    res1 = bootstrap_cold_start(
        db_path=mock_db_path,
        brain_dir=mock_brain_dir,
        output_memory_dir=output_mem_dir,
        dry_run=False,
        force=False,
    )
    assert res1["status"] == "completed"

    # Second run without force: should skip
    res2 = bootstrap_cold_start(
        db_path=mock_db_path,
        brain_dir=mock_brain_dir,
        output_memory_dir=output_mem_dir,
        dry_run=False,
        force=False,
    )
    assert res2["status"] == "skipped"
    assert res2["reason"] == "already_completed"

    # Third run with force: should re-run
    res3 = bootstrap_cold_start(
        db_path=mock_db_path,
        brain_dir=mock_brain_dir,
        output_memory_dir=output_mem_dir,
        dry_run=False,
        force=True,
    )
    assert res3["status"] == "completed"


def test_bootstrap_cold_start_empty_database(tmp_path: Path) -> None:
    """Verifies graceful handling when the SQLite database has 0 root sessions."""
    empty_db = tmp_path / "empty.db"
    conn = sqlite3.connect(str(empty_db))
    conn.execute(
        """
        CREATE TABLE conversation_summaries (
            conversation_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT "",
            preview TEXT NOT NULL DEFAULT "",
            step_count INTEGER NOT NULL DEFAULT 0,
            last_modified_time DATETIME NOT NULL,
            workspace_uris TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT "",
            source TEXT NOT NULL DEFAULT "",
            project_id TEXT NOT NULL DEFAULT "",
            agent_name TEXT NOT NULL DEFAULT "",
            parent_conversation_id TEXT NOT NULL DEFAULT "",
            nesting_depth INTEGER NOT NULL DEFAULT 0,
            last_user_input_time DATETIME NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()

    result = bootstrap_cold_start(
        db_path=empty_db,
        brain_dir=tmp_path / "brain",
        output_memory_dir=tmp_path / "memory",
        dry_run=False,
    )

    assert result["status"] == "completed"
    assert result["reason"] == "no_root_sessions"
    assert result["total_sessions"] == 0


# ============================================================================
# CLI Tests
# ============================================================================


def test_cli_dry_run_nominal(
    mock_db_path: Path,
    mock_brain_dir: Path,
    tmp_path: Path,
) -> None:
    """Verifies that the CLI executes cleanly with nominal arguments."""
    cli_mem = tmp_path / "cli_mem"
    code = main(
        [
            "--db-path",
            str(mock_db_path),
            "--brain-dir",
            str(mock_brain_dir),
            "--output-dir",
            str(cli_mem),
            "--dry-run",
            "--verbose",
        ]
    )
    assert code == 0


def test_cli_invalid_database(tmp_path: Path) -> None:
    """Verifies that the CLI returns non-zero code when database path is invalid."""
    code = main(
        [
            "--db-path",
            str(tmp_path / "non_existent.db"),
            "--dry-run",
        ]
    )
    assert code == 1


# ============================================================================
# Live Database Smoke Test
# ============================================================================


def test_live_database_cold_start_dry_run(tmp_path: Path) -> None:
    """Executes a real dry-run pass against live conversation_summaries.db if present.

    Guarantees that real-world transcripts and workspace URIs can be partitioned,
    distilled, clustered, and formatted into the manifest with 0 unhandled exceptions.
    """
    if not DEFAULT_DB_PATH.is_file():
        pytest.skip(f"Live database not present at {DEFAULT_DB_PATH}")

    output_dir = tmp_path / "live_memory"
    result = bootstrap_cold_start(
        db_path=DEFAULT_DB_PATH,
        brain_dir=DEFAULT_BRAIN_DIR,
        output_memory_dir=output_dir,
        dry_run=True,
        force=True,
    )

    assert result["status"] == "dry_run_completed"
    assert result["total_sessions"] >= 0
    assert len(result["created_files"]) >= 0

    manifest = result["catalog_content"]
    assert "# Cold-Start Memory Catalog" in manifest
