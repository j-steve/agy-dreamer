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

"""Comprehensive unit test suite for scripts/dream_helpers.py."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.dream_helpers import (
    DEFAULT_DB_PATH,
    CompactTranscript,
    DreamState,
    KeyedInvariant,
    SessionSummary,
    clean_user_prompt,
    extract_compact_transcript,
    extract_project_slug,
    extract_user_prompts,
    get_readonly_connection,
    get_session_by_id,
    list_active_memory_files,
    load_state,
    parse_workspace_uris,
    query_root_sessions,
    resolve_transcript_path,
    save_state_atomic,
    scan_keyed_invariants,
    update_state_watermark,
    uri_to_local_path,
)

# ============================================================================
# Category A Tests: SQLite Database Operations
# ============================================================================


def test_get_readonly_connection_success(mock_db_path: Path) -> None:
    """Verifies that get_readonly_connection opens SQLite in read-only mode."""
    conn = get_readonly_connection(mock_db_path)
    try:
        # Check row factory and busy timeout
        row = conn.execute("PRAGMA busy_timeout;").fetchone()
        assert row[0] == 5000

        # Verify reading works
        count_row = conn.execute(
            "SELECT count(*) AS cnt FROM conversation_summaries;"
        ).fetchone()
        assert count_row["cnt"] == 6

        # Enforce that write operations are rejected by SQLite readonly mode
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("CREATE TABLE forbidden (x int);")
    finally:
        conn.close()


def test_get_readonly_connection_missing_file(tmp_path: Path) -> None:
    """Verifies FileNotFoundError is raised when database file does not exist."""
    missing_file = tmp_path / "non_existent.db"
    with pytest.raises(FileNotFoundError, match="Database file not found"):
        get_readonly_connection(missing_file)


def test_get_readonly_connection_memory() -> None:
    """Verifies in-memory connection support for testing."""
    conn = get_readonly_connection(":memory:")
    try:
        assert conn.row_factory == sqlite3.Row
    finally:
        conn.close()


def test_query_root_sessions_filters_nesting_depth(mock_db_path: Path) -> None:
    """Verifies that query_root_sessions returns only root sessions (nesting_depth == 0)."""
    # mock_db has 4 root sessions and 2 subagent sessions (depth 1, depth 2)
    # By default, min_step_count=1 excludes empty shell root-session-4 (step_count=0)
    # and exclude_running=True excludes root-session-3 (running)
    results = query_root_sessions(
        db_path=mock_db_path, exclude_running=True, min_step_count=1
    )
    cids = [s.conversation_id for s in results]
    assert "root-session-1" in cids
    assert "root-session-2" in cids
    assert "subagent-depth-1" not in cids
    assert "subagent-depth-2" not in cids
    assert all(s.nesting_depth == 0 for s in results)


def test_query_root_sessions_running_filter(mock_db_path: Path) -> None:
    """Verifies exclude_running toggle."""
    # When exclude_running=False, root-session-3 should be included
    results_all = query_root_sessions(
        db_path=mock_db_path, exclude_running=False, min_step_count=1
    )
    cids_all = [s.conversation_id for s in results_all]
    assert "root-session-3" in cids_all

    # When exclude_running=True, root-session-3 must be excluded
    results_idle = query_root_sessions(
        db_path=mock_db_path, exclude_running=True, min_step_count=1
    )
    cids_idle = [s.conversation_id for s in results_idle]
    assert "root-session-3" not in cids_idle


def test_query_root_sessions_step_count_filter(mock_db_path: Path) -> None:
    """Verifies min_step_count filter."""
    # root-session-4 has step_count == 0
    results_with_zero = query_root_sessions(
        db_path=mock_db_path, exclude_running=False, min_step_count=0
    )
    cids_with_zero = [s.conversation_id for s in results_with_zero]
    assert "root-session-4" in cids_with_zero

    results_no_zero = query_root_sessions(
        db_path=mock_db_path, exclude_running=False, min_step_count=1
    )
    cids_no_zero = [s.conversation_id for s in results_no_zero]
    assert "root-session-4" not in cids_no_zero


def test_query_root_sessions_since_filter(mock_db_path: Path) -> None:
    """Verifies filtering by watermark timestamp."""
    # root-session-1 is at 2026-09-25 10:00:00
    # root-session-2 is at 2026-09-26 12:00:00
    since_dt = datetime(2026, 9, 26, 0, 0, 0, tzinfo=timezone.utc)
    results = query_root_sessions(
        since=since_dt, db_path=mock_db_path, exclude_running=False
    )
    cids = [s.conversation_id for s in results]
    assert "root-session-1" not in cids
    assert "root-session-2" in cids


def test_query_root_sessions_parameter_flexibility(mock_db_path: Path) -> None:
    """Verifies parameter handling when db_path is passed positionally first."""
    # Passing mock_db_path as first argument
    results = query_root_sessions(mock_db_path)
    assert len(results) >= 2
    assert results[0].conversation_id == "root-session-1"


def test_get_session_by_id(mock_db_path: Path) -> None:
    """Verifies fetching a single session by conversation_id."""
    session = get_session_by_id("root-session-1", db_path=mock_db_path)
    assert session is not None
    assert isinstance(session, SessionSummary)
    assert session.conversation_id == "root-session-1"
    assert session.title == "Service Dispatch"
    assert session.step_count == 50
    assert len(session.workspace_uris) == 1
    assert "service-dispatch" in session.workspace_uris[0]

    missing = get_session_by_id("non-existent-uuid", db_path=mock_db_path)
    assert missing is None


# ============================================================================
# Category B Tests: Workspace URI Normalization
# ============================================================================


def test_parse_workspace_uris_nominal() -> None:
    """Parses standard JSON array of workspace URIs."""
    raw = '["file:///c%3A/Projects/service-dispatch"]'
    parsed = parse_workspace_uris(raw)
    assert parsed == ["file:///c%3A/Projects/service-dispatch"]


def test_parse_workspace_uris_multiple() -> None:
    """Parses multi-URI JSON array."""
    raw = '["file:///c%3A/repo1", "file:///c%3A/repo2"]'
    parsed = parse_workspace_uris(raw)
    assert len(parsed) == 2
    assert parsed[0] == "file:///c%3A/repo1"
    assert parsed[1] == "file:///c%3A/repo2"


def test_parse_workspace_uris_edge_cases() -> None:
    """Handles empty strings, empty arrays, malformed JSON, and non-strings."""
    assert parse_workspace_uris("") == []
    assert parse_workspace_uris("[]") == []
    assert parse_workspace_uris("   ") == []
    assert parse_workspace_uris("{broken json") == []
    assert parse_workspace_uris(None) == []  # type: ignore


def test_uri_to_local_path_windows() -> None:
    """Converts percent-encoded Windows file URIs to native Windows paths."""
    uri = "file:///c%3A/Projects/service-dispatch"
    local_path = uri_to_local_path(uri)
    assert local_path == os.path.normpath(r"C:\Projects\service-dispatch")


def test_uri_to_local_path_special_characters() -> None:
    """Handles parentheses and spaces in URI."""
    uri = "file:///c%3A/Program%20Files%20%28x86%29/Steam/apps"
    local_path = uri_to_local_path(uri)
    assert local_path == os.path.normpath(r"C:\Program Files (x86)\Steam\apps")


def test_uri_to_local_path_plain_path() -> None:
    """Handles strings that are already plain local filesystem paths."""
    plain = r"C:\Projects\service-dispatch"
    assert uri_to_local_path(plain) == os.path.normpath(plain)


def test_uri_to_local_path_empty_and_invalid() -> None:
    """Handles empty or invalid input cleanly."""
    assert uri_to_local_path("") == ""
    assert uri_to_local_path(None) == ""  # type: ignore


def test_extract_project_slug() -> None:
    """Extracts project slugs from URIs and local paths."""
    uri = "file:///c%3A/Projects/sample-project"
    assert extract_project_slug(uri) == "sample-project"

    plain_path = r"C:\Projects\sample-pipeline"
    assert extract_project_slug(plain_path) == "sample-pipeline"
    assert extract_project_slug("") == ""


# ============================================================================
# Category C Tests: Transcript Streaming & Compaction
# ============================================================================


def test_resolve_transcript_path_exists(mock_brain_dir: Path) -> None:
    """Verifies resolving an existing session's transcript.jsonl."""
    resolved = resolve_transcript_path("root-session-1", brain_dir=mock_brain_dir)
    assert resolved is not None
    assert resolved.is_file()
    assert resolved.name == "transcript.jsonl"


def test_resolve_transcript_path_missing(mock_brain_dir: Path) -> None:
    """Verifies that missing session folders return None gracefully."""
    resolved = resolve_transcript_path("non-existent-session", brain_dir=mock_brain_dir)
    assert resolved is None
    assert resolve_transcript_path("", brain_dir=mock_brain_dir) is None


def test_clean_user_prompt_with_xml_tags() -> None:
    """Extracts prompt enclosed in <USER_REQUEST> tags."""
    raw = (
        "<USER_REQUEST>\n"
        "Build the dream helper engine.\n"
        "</USER_REQUEST>\n"
        "<ADDITIONAL_METADATA>\ntime: 2026-09-27\n</ADDITIONAL_METADATA>"
    )
    cleaned = clean_user_prompt(raw)
    assert cleaned == "Build the dream helper engine."


def test_clean_user_prompt_fallback_metadata_stripping() -> None:
    """Strips <ADDITIONAL_METADATA> and settings when <USER_REQUEST> is absent."""
    raw = (
        "Refactor database connection pool.\n"
        "<ADDITIONAL_METADATA>some data</ADDITIONAL_METADATA>\n"
        "<USER_SETTINGS_CHANGE>foo=bar</USER_SETTINGS_CHANGE>"
    )
    cleaned = clean_user_prompt(raw)
    assert cleaned == "Refactor database connection pool."


def test_clean_user_prompt_empty() -> None:
    """Handles empty or None strings."""
    assert clean_user_prompt("") == ""
    assert clean_user_prompt(None) == ""  # type: ignore


def test_extract_user_prompts(mock_brain_dir: Path) -> None:
    """Extracts all user prompts from a session transcript."""
    prompts = extract_user_prompts("root-session-1", brain_dir=mock_brain_dir)
    assert len(prompts) == 2
    assert "Implement the service router contract for ServiceDispatch." in prompts[0]
    assert "Also ensure no backwards compatibility shims are added." in prompts[1]


def test_extract_compact_transcript_nominal(mock_brain_dir: Path) -> None:
    """Extracts compact transcript structure from a full session log."""
    compact = extract_compact_transcript("root-session-1", brain_dir=mock_brain_dir)
    assert isinstance(compact, CompactTranscript)
    assert compact.conversation_id == "root-session-1"
    assert len(compact.user_prompts) == 2
    assert len(compact.agent_thoughts) == 2
    assert "Need to establish protocol contracts" in compact.agent_thoughts[0]
    assert len(compact.planner_goals) == 2
    assert "Define Router Protocol" in compact.planner_goals

    # Tool summaries should contain toolAction, toolSummary, status, target
    assert len(compact.tool_summaries) == 2
    t1 = compact.tool_summaries[0]
    assert t1["tool"] == "write_to_file"
    assert t1["toolAction"] == "Writing router file"
    assert t1["toolSummary"] == "Write service router"
    assert "router.py" in t1["target"]

    # Verify that multi-megabyte GENERIC.content was strictly NOT stored
    all_text = json.dumps(compact.tool_summaries)
    assert "Simulated multi-megabyte stdout" not in all_text


def test_extract_compact_transcript_strips_multi_mb_payload(
    mock_brain_dir: Path,
) -> None:
    """Verifies that 3 MB simulated tool outputs are completely stripped."""
    compact = extract_compact_transcript("root-session-large", brain_dir=mock_brain_dir)
    assert compact.conversation_id == "root-session-large"
    assert len(compact.user_prompts) == 1
    assert len(compact.tool_summaries) == 1
    # Check that the 3 MB 'Z' characters were stripped and not included
    dumped = json.dumps(
        {
            "prompts": compact.user_prompts,
            "thoughts": compact.agent_thoughts,
            "tools": compact.tool_summaries,
        }
    )
    assert len(dumped) < 5000  # Should be tiny (<5 KB), not 3 MB


def test_extract_compact_transcript_corrupted_lines(mock_brain_dir: Path) -> None:
    """Verifies that corrupted JSON lines and empty lines are skipped gracefully."""
    compact = extract_compact_transcript(
        "root-session-corrupted", brain_dir=mock_brain_dir
    )
    assert compact.conversation_id == "root-session-corrupted"
    assert len(compact.user_prompts) == 1
    assert compact.user_prompts[0] == "Fix bug"
    assert len(compact.agent_thoughts) == 1
    assert compact.agent_thoughts[0] == "Investigating..."


def test_extract_compact_transcript_missing_session(mock_brain_dir: Path) -> None:
    """Verifies missing session returns empty CompactTranscript or raises if requested."""
    compact = extract_compact_transcript(
        "missing-session-uuid", brain_dir=mock_brain_dir
    )
    assert compact.conversation_id == "missing-session-uuid"
    assert compact.user_prompts == []
    assert compact.tool_summaries == []

    with pytest.raises(FileNotFoundError, match="Transcript not found"):
        extract_compact_transcript(
            "missing-session-uuid",
            brain_dir=mock_brain_dir,
            raise_on_missing=True,
        )


def test_extract_compact_transcript_direct_path(mock_brain_dir: Path) -> None:
    """Verifies passing a direct Path to a transcript.jsonl file."""
    path = (
        mock_brain_dir
        / "root-session-1"
        / ".system_generated"
        / "logs"
        / "transcript.jsonl"
    )
    compact = extract_compact_transcript(path)
    assert compact.conversation_id == "root-session-1"
    assert len(compact.user_prompts) == 2


# ============================================================================
# Category D Tests: State Management
# ============================================================================


def test_load_state_nominal(mock_state_file: Path) -> None:
    """Loads a pre-populated state file."""
    state = load_state(mock_state_file)
    assert state.cold_start_completed is True
    assert state.last_consolidated_session_id == "root-session-2"
    assert "root-session-1" in state.processed_session_ids
    assert state.schema_version == 1
    assert state.stats["total_invariants_extracted"] == 3


def test_load_state_missing_file(tmp_path: Path) -> None:
    """Returns default initial DreamState if state file is missing."""
    missing = tmp_path / "memory" / ".missing_state.json"
    state = load_state(missing)
    assert state.cold_start_completed is False
    assert state.last_consolidated_timestamp == ""
    assert state.processed_session_ids == []
    assert state.schema_version == 1


def test_load_state_corrupted_json(tmp_path: Path) -> None:
    """Recovers safely from corrupted state JSON."""
    corrupted_file = tmp_path / "corrupted_state.json"
    corrupted_file.write_text("NOT_JSON{[[", encoding="utf-8")
    state = load_state(corrupted_file)
    assert state.cold_start_completed is False
    assert state.processed_session_ids == []


def test_save_state_atomic(tmp_path: Path) -> None:
    """Verifies atomic state saving and reload."""
    state_file = tmp_path / "memory" / ".state.json"
    state = DreamState(
        cold_start_completed=True,
        last_consolidated_timestamp="2026-09-27T20:00:00Z",
        last_consolidated_session_id="session-xyz",
        processed_session_ids=["session-abc", "session-xyz"],
        schema_version=1,
    )
    save_state_atomic(state, state_file)

    # Verify file exists on disk
    assert state_file.is_file()
    # Verify no dangling .tmp files in directory
    tmp_files = list(state_file.parent.glob("*.tmp"))
    assert len(tmp_files) == 0

    reloaded = load_state(state_file)
    assert reloaded.cold_start_completed is True
    assert reloaded.last_consolidated_timestamp == "2026-09-27T20:00:00Z"
    assert reloaded.last_consolidated_session_id == "session-xyz"
    assert reloaded.processed_session_ids == ["session-abc", "session-xyz"]


def test_update_state_watermark(tmp_path: Path) -> None:
    """Verifies updating watermark and appending new processed session IDs."""
    state_file = tmp_path / "memory" / ".state.json"
    initial_state = DreamState(
        cold_start_completed=True,
        last_consolidated_timestamp="2026-09-25T00:00:00Z",
        processed_session_ids=["session-1"],
    )
    save_state_atomic(initial_state, state_file)

    updated = update_state_watermark(
        state_file=state_file,
        watermark="2026-09-27T12:00:00Z",
        processed_ids=["session-1", "session-2", "session-3"],
    )

    assert updated.last_consolidated_timestamp == "2026-09-27T12:00:00Z"
    assert updated.last_consolidated_session_id == "session-3"
    assert updated.processed_session_ids == [
        "session-1",
        "session-2",
        "session-3",
    ]


# ============================================================================
# Category E Tests: Manifest & Invariant Scanning
# ============================================================================


def test_scan_keyed_invariants_nominal(mock_memory_dir: Path) -> None:
    """Scans and extracts multiple Keyed Invariants from a markdown file."""
    sample_file = mock_memory_dir / "projects" / "sample-project.md"
    content = sample_file.read_text(encoding="utf-8")
    invariants = scan_keyed_invariants(content, file_path=str(sample_file))

    assert len(invariants) == 2

    inv1 = invariants[0]
    assert isinstance(inv1, KeyedInvariant)
    assert inv1.key == "sample_project.contour_integrity"
    assert "2026-09-27" in inv1.last_confirmed
    assert inv1.supersedes == "sample_project.old_contour"
    assert "GeometryModel" in inv1.target
    assert "genuine multi-point polygons" in inv1.invariant
    assert "Rectangular bounding boxes" in inv1.negative_constraint
    assert "downstream cv" in inv1.rationale.lower()
    assert inv1.file_path == str(sample_file)

    inv2 = invariants[1]
    assert inv2.key == "sample_project.model_runtime"
    assert inv2.supersedes is None
    assert "Neural model" in inv2.target
    assert "fp16" in inv2.invariant


def test_scan_keyed_invariants_empty_and_none() -> None:
    """Handles empty content or non-matching content."""
    assert scan_keyed_invariants("") == []
    assert scan_keyed_invariants(None) == []  # type: ignore
    assert scan_keyed_invariants("# Just regular markdown without tags") == []


def test_list_active_memory_files(mock_memory_dir: Path) -> None:
    """Lists active markdown files while excluding archive/ by default."""
    active_files = list_active_memory_files(mock_memory_dir)
    file_names = [f.name for f in active_files]

    assert "preferences.md" in file_names
    assert "guardrails.md" in file_names
    assert "sample-project.md" in file_names
    assert "cloud-infra.md" in file_names
    assert "2026-09-28.md" in file_names
    # archive/superseded.md must be excluded by default
    assert "superseded.md" not in file_names


def test_list_active_memory_files_exclude_proposals(
    mock_memory_dir: Path,
) -> None:
    """Verifies exclude_proposals toggle."""
    active_no_proposals = list_active_memory_files(
        mock_memory_dir, exclude_proposals=True
    )
    names = [f.name for f in active_no_proposals]
    assert "2026-09-28.md" not in names
    assert "sample-project.md" in names


# ============================================================================
# Live Database Integration Test (Optional / Environment Aware)
# ============================================================================


def test_live_database_query_integration() -> None:
    """Integration test against live conversation_summaries.db if present."""
    if not DEFAULT_DB_PATH.is_file():
        pytest.skip("Live database not present in this test environment.")

    sessions = query_root_sessions(
        db_path=DEFAULT_DB_PATH, exclude_running=False, min_step_count=0
    )
    assert len(sessions) >= 0
    assert all(s.nesting_depth == 0 for s in sessions)
    assert all(isinstance(s.last_modified_time, datetime) for s in sessions)
