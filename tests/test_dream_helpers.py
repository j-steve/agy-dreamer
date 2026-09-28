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
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from scripts.dream_helpers import (
    DEFAULT_DB_PATH,
    CompactTranscript,
    CompactTurn,
    DreamState,
    KeyedInvariant,
    SessionSummary,
    _build_root_sessions_query,
    _extract_tool_summary,
    _normalize_watermark_datetime,
    _parse_iso_datetime,
    _render_turn_markdown,
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


def test_compact_turn_dataclass_model() -> None:
    """Verifies CompactTurn attributes, defaults, and dictionary serialization."""
    turn = CompactTurn(
        step_index=5,
        created_at="2026-09-28T14:30:00Z",
        turn_type="agent",
        content="Analyzing architecture constraints.",
        is_new=True,
        goals=["Refactor Router", "Add Tests"],
        tool_summaries=[{"tool": "run_command", "status": "DONE"}],
    )
    assert turn.step_index == 5
    assert turn.created_at == "2026-09-28T14:30:00Z"
    assert turn.turn_type == "agent"
    assert turn.content == "Analyzing architecture constraints."
    assert turn.is_new is True
    assert turn.goals == ["Refactor Router", "Add Tests"]
    assert len(turn.tool_summaries) == 1

    d = turn.to_dict()
    assert d["step_index"] == 5
    assert d["created_at"] == "2026-09-28T14:30:00Z"
    assert d["turn_type"] == "agent"
    assert d["is_new"] is True

    # Test default values
    default_turn = CompactTurn()
    assert default_turn.step_index == 0
    assert default_turn.created_at == ""
    assert default_turn.turn_type == "user"
    assert default_turn.content == ""
    assert default_turn.is_new is True
    assert default_turn.goals == []
    assert default_turn.tool_summaries == []


def test_extract_compact_transcript_watermark_partitioning(tmp_path: Path) -> None:
    """Verifies turns <= watermark are marked is_new=False and turns > watermark are is_new=True."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        # Turn 0: Prior context (before watermark)
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "created_at": "2026-09-20T10:00:00Z",
                "content": "Initial user request from earlier day.",
            }
        ),
        # Turn 1: Prior context (before watermark)
        json.dumps(
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 1,
                "created_at": "2026-09-20T10:01:00Z",
                "thinking": "Initial agent thinking from earlier day.",
            }
        ),
        # Turn 2: Prior context (boundary: exactly equal to watermark)
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 2,
                "created_at": "2026-09-22T12:00:00Z",
                "content": "Request at exact watermark boundary.",
            }
        ),
        # Turn 3: New activity (after watermark)
        json.dumps(
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 3,
                "created_at": "2026-09-22T12:05:00Z",
                "thinking": "Response strictly after watermark.",
            }
        ),
        # Turn 4: New activity (after watermark)
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 4,
                "created_at": "2026-09-25T09:00:00Z",
                "content": "Latest user request.",
            }
        ),
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    compact = extract_compact_transcript(
        transcript_file,
        watermark="2026-09-22T12:00:00Z",
        prior_context_turns=10,
    )

    assert len(compact.turns) == 5
    # Historical turns on or before watermark
    assert compact.turns[0].is_new is False
    assert compact.turns[0].step_index == 0
    assert compact.turns[1].is_new is False
    assert compact.turns[1].step_index == 1
    assert compact.turns[2].is_new is False
    assert compact.turns[2].step_index == 2

    # New activity turns after watermark
    assert compact.turns[3].is_new is True
    assert compact.turns[3].step_index == 3
    assert compact.turns[4].is_new is True
    assert compact.turns[4].step_index == 4

    assert len(compact.prior_context) == 3
    assert len(compact.new_activity) == 2


def test_extract_compact_transcript_watermark_none(tmp_path: Path) -> None:
    """Verifies that when watermark is None, all turns are classified as new activity."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "created_at": "2026-09-20T10:00:00Z",
                "content": "Turn 0",
            }
        ),
        json.dumps(
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 1,
                "created_at": "2026-09-20T10:01:00Z",
                "thinking": "Turn 1",
            }
        ),
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    compact = extract_compact_transcript(transcript_file, watermark=None)
    assert len(compact.turns) == 2
    assert all(t.is_new for t in compact.turns)
    assert compact.prior_context == []
    assert len(compact.new_activity) == 2


def test_extract_compact_transcript_prior_context_bounding_pruning(
    tmp_path: Path,
) -> None:
    """Verifies historical turns exceeding prior_context_turns are pruned to prevent bloat."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = []
    # 8 historical turns (Turn 0 to Turn 7)
    for i in range(8):
        lines.append(
            json.dumps(
                {
                    "type": "USER_INPUT" if i % 2 == 0 else "PLANNER_RESPONSE",
                    "step_index": i,
                    "created_at": f"2026-09-1{i:01d}T10:00:00Z",
                    "content" if i % 2 == 0 else "thinking": f"Historical turn {i}",
                }
            )
        )
    # 2 new activity turns (Turn 8 and Turn 9)
    for i in (8, 9):
        lines.append(
            json.dumps(
                {
                    "type": "USER_INPUT" if i % 2 == 0 else "PLANNER_RESPONSE",
                    "step_index": i,
                    "created_at": f"2026-09-2{i:01d}T10:00:00Z",
                    "content" if i % 2 == 0 else "thinking": f"New turn {i}",
                }
            )
        )
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    # Watermark set between turn 7 and turn 8; bound prior context to 3 turns
    compact = extract_compact_transcript(
        transcript_file,
        watermark="2026-09-18T00:00:00Z",
        prior_context_turns=3,
    )

    # Out of 8 historical turns, only the most recent 3 (turns 5, 6, 7) must remain
    assert len(compact.prior_context) == 3
    assert [t.step_index for t in compact.prior_context] == [5, 6, 7]
    assert all(not t.is_new for t in compact.prior_context)

    # All new activity turns (turns 8, 9) must remain
    assert len(compact.new_activity) == 2
    assert [t.step_index for t in compact.new_activity] == [8, 9]
    assert all(t.is_new for t in compact.new_activity)

    # Total turns in compact structure is 3 + 2 = 5
    assert len(compact.turns) == 5


def test_extract_compact_transcript_prior_context_zero_bound(tmp_path: Path) -> None:
    """Verifies prior_context_turns=0 prunes all historical turns from prior context."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "created_at": "2026-09-20T10:00:00Z",
                "content": "Turn 0",
            }
        ),
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 1,
                "created_at": "2026-09-25T10:00:00Z",
                "content": "Turn 1",
            }
        ),
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    compact = extract_compact_transcript(
        transcript_file,
        watermark="2026-09-22T00:00:00Z",
        prior_context_turns=0,
    )
    assert compact.prior_context == []
    assert len(compact.new_activity) == 1
    assert len(compact.turns) == 1
    assert compact.turns[0].step_index == 1


def test_extract_compact_transcript_prior_context_fewer_than_bound(
    tmp_path: Path,
) -> None:
    """Verifies that all historical turns are preserved when count is below prior_context_turns."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "created_at": "2026-09-20T10:00:00Z",
                "content": "Turn 0",
            }
        ),
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 1,
                "created_at": "2026-09-25T10:00:00Z",
                "content": "Turn 1",
            }
        ),
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    compact = extract_compact_transcript(
        transcript_file,
        watermark="2026-09-22T00:00:00Z",
        prior_context_turns=5,
    )
    assert len(compact.prior_context) == 1
    assert compact.prior_context[0].step_index == 0
    assert len(compact.new_activity) == 1
    assert compact.new_activity[0].step_index == 1


def test_render_partitioned_markdown_structure(tmp_path: Path) -> None:
    """Verifies render_partitioned_markdown outputs valid Markdown with timestamps and sections."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "created_at": "2026-09-20T10:00:00.0000000+00:00",
                "content": "Historical architecture prompt.",
            }
        ),
        json.dumps(
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 1,
                "created_at": "2026-09-20T10:05:00.0000000+00:00",
                "thinking": "Designing architectural protocol.",
                "plan": ["Draft Router Spec"],
                "tool_calls": [
                    {
                        "name": "write_to_file",
                        "args": {
                            "TargetFile": "src/router.py",
                            "toolAction": "Writing router",
                            "toolSummary": "Write service router",
                        },
                        "status": "DONE",
                    }
                ],
            }
        ),
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 2,
                "created_at": "2026-09-25T14:30:00.0000000+00:00",
                "content": "New request: add payload validator.",
            }
        ),
        json.dumps(
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 3,
                "created_at": "2026-09-25T14:32:00.0000000+00:00",
                "thinking": "Implementing validator.",
                "plan": ["Implement Validator"],
                "tool_calls": [
                    {
                        "name": "run_command",
                        "args": {
                            "CommandLine": "pytest tests/test_validator.py",
                            "toolAction": "Running validator tests",
                            "toolSummary": "Run validator tests",
                        },
                        "status": "DONE",
                    }
                ],
            }
        ),
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    compact = extract_compact_transcript(
        transcript_file,
        watermark="2026-09-22T00:00:00Z",
        prior_context_turns=4,
    )
    md = compact.render_partitioned_markdown()

    # Section Headers
    assert "### Prior Context" in md
    assert "### New Activity" in md

    # Check that Prior Context section appears before New Activity section
    assert md.index("### Prior Context") < md.index("### New Activity")

    # Timestamp format [YYYY-MM-DD HH:MM]
    assert "[2026-09-20 10:00]" in md
    assert "[2026-09-20 10:05]" in md
    assert "[2026-09-25 14:30]" in md
    assert "[2026-09-25 14:32]" in md

    # Turn headers
    assert "#### [2026-09-20 10:00] User" in md
    assert "#### [2026-09-20 10:05] Agent" in md
    assert "#### [2026-09-25 14:30] User" in md
    assert "#### [2026-09-25 14:32] Agent" in md

    # Contents and Goals/Tools formatting
    assert "Historical architecture prompt." in md
    assert "Draft Router Spec" in md
    assert "Write service router" in md
    assert "src/router.py" in md
    assert "New request: add payload validator." in md
    assert "Run validator tests" in md


def test_render_partitioned_markdown_empty_sections() -> None:
    """Verifies render_partitioned_markdown handles transcripts with empty sections gracefully."""
    empty = CompactTranscript(
        conversation_id="empty-1",
        user_prompts=[],
        agent_thoughts=[],
        planner_goals=[],
        tool_summaries=[],
    )
    md_empty = empty.render_partitioned_markdown()
    assert "### Prior Context" in md_empty
    assert "*(No prior context)*" in md_empty
    assert "### New Activity" in md_empty
    assert "*(No new activity)*" in md_empty

    only_prior = CompactTranscript(
        conversation_id="prior-only",
        user_prompts=["Prior prompt"],
        agent_thoughts=[],
        planner_goals=[],
        tool_summaries=[],
        turns=[
            CompactTurn(
                step_index=0,
                created_at="2026-09-20T10:00:00Z",
                turn_type="user",
                content="Prior prompt",
                is_new=False,
            )
        ],
    )
    md_prior = only_prior.render_partitioned_markdown()
    assert "#### [2026-09-20 10:00] User" in md_prior
    assert "*(No new activity)*" in md_prior


def test_extract_compact_transcript_datetime_watermark(tmp_path: Path) -> None:
    """Verifies extract_compact_transcript accepts datetime objects as watermark."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "created_at": "2026-09-20T10:00:00Z",
                "content": "Early prompt",
            }
        ),
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 1,
                "created_at": "2026-09-25T10:00:00Z",
                "content": "Late prompt",
            }
        ),
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    # Timezone-aware datetime
    dt_aware = datetime(2026, 9, 22, 0, 0, 0, tzinfo=timezone.utc)
    compact_aware = extract_compact_transcript(transcript_file, watermark=dt_aware)
    assert len(compact_aware.prior_context) == 1
    assert len(compact_aware.new_activity) == 1

    # Naive datetime
    dt_naive = datetime(2026, 9, 22, 0, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    compact_naive = extract_compact_transcript(transcript_file, watermark=dt_naive)
    assert len(compact_naive.prior_context) == 1
    assert len(compact_naive.new_activity) == 1


def test_extract_turn_timestamp_avoids_user_prompt_false_match(tmp_path: Path) -> None:
    """Verifies timestamp parsing isolates ADDITIONAL_METADATA and ignores prompt text with time:."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "content": (
                    "<USER_REQUEST>\n"
                    "At that time: I wanted to build an isolated microservice.\n"
                    "</USER_REQUEST>\n"
                    "<ADDITIONAL_METADATA>\n"
                    "The current local time is: 2026-09-28T11:57:12-06:00.\n"
                    "</ADDITIONAL_METADATA>"
                ),
            }
        )
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    compact = extract_compact_transcript(transcript_file)
    assert len(compact.turns) == 1
    assert compact.turns[0].created_at == "2026-09-28T11:57:12-06:00"
    md = compact.render_partitioned_markdown()
    assert "[2026-09-28 11:57]" in md
    assert "[I wanted to build" not in md


def test_extract_compact_transcript_propagates_timestamp_to_agent_turns(
    tmp_path: Path,
) -> None:
    """Verifies agent turns without explicit created_at inherit conversational timestamps."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        # Turn 0: User turn with explicit timestamp
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "created_at": "2026-09-20T10:00:00Z",
                "content": "Historical architecture prompt.",
            }
        ),
        # Turn 1: Agent response without explicit timestamp field
        json.dumps(
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 1,
                "thinking": "Designing historical architecture.",
            }
        ),
        # Turn 2: User turn with explicit timestamp
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 2,
                "created_at": "2026-09-20T10:05:00Z",
                "content": "Follow-up historical instruction.",
            }
        ),
        # Turn 3: Agent response without explicit timestamp field
        json.dumps(
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 3,
                "thinking": "Refining historical design.",
            }
        ),
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    # Watermark set to 2026-09-22; all 4 turns occurred on 2026-09-20
    compact = extract_compact_transcript(
        transcript_file,
        watermark="2026-09-22T00:00:00Z",
        prior_context_turns=10,
    )

    # All 4 turns must be classified as Prior Context
    assert len(compact.prior_context) == 4
    assert len(compact.new_activity) == 0
    assert all(not t.is_new for t in compact.turns)

    # Agent turns must have inherited timestamps and not be undated
    assert compact.turns[1].created_at == "2026-09-20T10:00:00Z"
    assert compact.turns[3].created_at == "2026-09-20T10:05:00Z"

    md = compact.render_partitioned_markdown()
    assert "[Undated]" not in md
    assert "[2026-09-20 10:00]" in md
    assert "[2026-09-20 10:05]" in md


def test_extract_compact_transcript_backfills_leading_undated_turn(
    tmp_path: Path,
) -> None:
    """Verifies leading turns without timestamps inherit the first discovered timestamp."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        # Turn 0: User turn without timestamp
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "content": "Prompt without timestamp.",
            }
        ),
        # Turn 1: Agent turn with explicit timestamp
        json.dumps(
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 1,
                "created_at": "2026-09-20T10:00:00Z",
                "thinking": "First turn with timestamp.",
            }
        ),
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    compact = extract_compact_transcript(
        transcript_file,
        watermark="2026-09-22T00:00:00Z",
    )
    assert len(compact.prior_context) == 2
    assert len(compact.new_activity) == 0
    assert compact.turns[0].created_at == "2026-09-20T10:00:00Z"
    assert compact.turns[0].is_new is False


def test_extract_compact_transcript_empty_watermark_string(tmp_path: Path) -> None:
    """Verifies empty or whitespace watermark string is normalized to None (all turns new)."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "created_at": "2026-09-20T10:00:00Z",
                "content": "Turn 0",
            }
        ),
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    compact_empty = extract_compact_transcript(transcript_file, watermark="")
    assert len(compact_empty.new_activity) == 1
    assert compact_empty.prior_context == []

    compact_ws = extract_compact_transcript(transcript_file, watermark="   ")
    assert len(compact_ws.new_activity) == 1
    assert compact_ws.prior_context == []


def test_extract_compact_transcript_skips_empty_planner_records(
    tmp_path: Path,
) -> None:
    """Verifies planner records with no thinking, content, goals, or tools are skipped."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "created_at": "2026-09-20T10:00:00Z",
                "content": "User prompt.",
            }
        ),
        json.dumps(
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 1,
                "status": "DONE",
            }
        ),
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    compact = extract_compact_transcript(transcript_file)
    assert len(compact.turns) == 1
    assert compact.turns[0].turn_type == "user"


def test_compact_transcript_to_dict() -> None:
    """Verifies serialization of CompactTranscript to a dictionary."""
    transcript = CompactTranscript(
        conversation_id="conv-123",
        user_prompts=["Prompt 1"],
        agent_thoughts=["Thought 1"],
        planner_goals=["Goal 1"],
        tool_summaries=[{"tool": "run_command", "summary": "Run tests"}],
        turns=[
            CompactTurn(
                step_index=0,
                created_at="2026-09-20T10:00:00Z",
                turn_type="user",
                content="Prompt 1",
                is_new=False,
            )
        ],
    )
    d = transcript.to_dict()
    assert d["conversation_id"] == "conv-123"
    assert d["user_prompts"] == ["Prompt 1"]
    assert len(d["turns"]) == 1
    assert d["turns"][0]["step_index"] == 0


def test_compact_transcript_new_activity_fallback_with_goals_tools() -> None:
    """Verifies that legacy or turnless CompactTranscript preserves goals/tools in new_activity."""
    transcript = CompactTranscript(
        conversation_id="conv-legacy",
        user_prompts=["Build microservice"],
        agent_thoughts=["Scaffolding directory"],
        planner_goals=["Draft service router"],
        tool_summaries=[{"tool": "write_to_file", "summary": "Create router.py"}],
    )
    # turns is empty, fallback should synthesize turns
    assert len(transcript.turns) == 0
    new_turns = transcript.new_activity
    assert len(new_turns) == 2
    assert new_turns[0].turn_type == "user"
    assert new_turns[0].content == "Build microservice"
    assert new_turns[1].turn_type == "agent"
    assert new_turns[1].content == "Scaffolding directory"
    assert new_turns[1].goals == ["Draft service router"]
    assert len(new_turns[1].tool_summaries) == 1


def test_extract_compact_transcript_whitespace_timestamp(tmp_path: Path) -> None:
    """Verifies whitespace timestamps are treated as undated/new activity and not year 0001."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "created_at": "   ",
                "content": "Turn with whitespace timestamp.",
            }
        ),
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    compact = extract_compact_transcript(
        transcript_file,
        watermark="2026-09-22T00:00:00Z",
    )
    assert len(compact.new_activity) == 1
    assert compact.prior_context == []
    assert compact.turns[0].is_new is True

    md = compact.render_partitioned_markdown()
    assert "[Undated]" in md
    assert "[0001-01-01" not in md


def test_extract_compact_transcript_fallback_on_whitespace_created_at(
    tmp_path: Path,
) -> None:
    """Verifies that whitespace created_at falls back to timestamp or time fields."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "created_at": "  ",
                "timestamp": "2026-09-25T14:00:00Z",
                "content": "Turn with fallback timestamp.",
            }
        ),
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    compact = extract_compact_transcript(
        transcript_file,
        watermark="2026-09-22T00:00:00Z",
    )
    assert len(compact.new_activity) == 1
    assert compact.turns[0].created_at == "2026-09-25T14:00:00Z"
    md = compact.render_partitioned_markdown()
    assert "[2026-09-25 14:00]" in md


def test_extract_compact_transcript_trailing_dot_and_metadata_variations(
    tmp_path: Path,
) -> None:
    """Verifies metadata timestamps with trailing dots and phrasing variations are parsed cleanly."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "content": (
                    "<USER_REQUEST>First prompt</USER_REQUEST>\n"
                    "<ADDITIONAL_METADATA>\ntime: 2026-09-20T10:00:00Z.\n</ADDITIONAL_METADATA>"
                ),
            }
        ),
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 1,
                "content": (
                    "<USER_REQUEST>Second prompt</USER_REQUEST>\n"
                    "<ADDITIONAL_METADATA>\nThe current time is: 2026-09-25T12:00:00Z.\n</ADDITIONAL_METADATA>"
                ),
            }
        ),
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 2,
                "metadata": {"created_at": "2026-09-25T15:00:00Z"},
                "content": "Third prompt with dict metadata",
            }
        ),
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    compact = extract_compact_transcript(
        transcript_file,
        watermark="2026-09-22T00:00:00Z",
    )
    assert len(compact.prior_context) == 1
    assert len(compact.new_activity) == 2
    assert compact.turns[0].created_at == "2026-09-20T10:00:00Z"
    assert compact.turns[1].created_at == "2026-09-25T12:00:00Z"
    assert compact.turns[2].created_at == "2026-09-25T15:00:00Z"


def test_extract_compact_transcript_date_object_watermark(tmp_path: Path) -> None:
    """Verifies extract_compact_transcript accepts datetime.date objects as watermark."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "created_at": "2026-09-20T10:00:00Z",
                "content": "Early turn",
            }
        ),
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 1,
                "created_at": "2026-09-25T10:00:00Z",
                "content": "Late turn",
            }
        ),
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    compact = extract_compact_transcript(
        transcript_file,
        watermark=date(2026, 9, 22),
    )
    assert len(compact.prior_context) == 1
    assert len(compact.new_activity) == 1
    assert compact.turns[0].is_new is False
    assert compact.turns[1].is_new is True


def test_extract_compact_transcript_tool_calls_json_string_args(
    tmp_path: Path,
) -> None:
    """Verifies tool call records with serialized JSON string arguments are parsed."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 0,
                "created_at": "2026-09-28T12:00:00Z",
                "thinking": "Invoking tool with stringified JSON arguments.",
                "tool_calls": [
                    {
                        "name": "run_command",
                        "args": json.dumps(
                            {
                                "toolAction": "Running test suite",
                                "toolSummary": "Run pytest suite",
                                "CommandLine": "pytest tests/",
                            }
                        ),
                        "status": "DONE",
                    }
                ],
            }
        ),
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    compact = extract_compact_transcript(transcript_file)
    assert len(compact.tool_summaries) == 1
    tool = compact.tool_summaries[0]
    assert tool["tool"] == "run_command"
    assert tool["toolAction"] == "Running test suite"
    assert tool["toolSummary"] == "Run pytest suite"
    assert "pytest tests/" in tool["target"]


def test_render_partitioned_markdown_assistant_and_non_dict_tools() -> None:
    """Verifies markdown rendering for assistant turn_type and handles non-dict tools defensively."""
    transcript = CompactTranscript(
        conversation_id="conv-assist",
        user_prompts=[],
        agent_thoughts=[],
        planner_goals=[],
        tool_summaries=[],
        turns=[
            CompactTurn(
                step_index=0,
                created_at="2026-09-28T12:00:00Z",
                turn_type="assistant",
                content="Assistant response text.",
                is_new=True,
                tool_summaries=["custom_tool_identifier"],  # type: ignore[arg-type]
            )
        ],
    )
    md = transcript.render_partitioned_markdown()
    assert "#### [2026-09-28 12:00] Agent" in md
    assert "Assistant response text." in md
    assert "- `custom_tool_identifier`" in md


def test_normalize_watermark_sentinels_and_unparseable() -> None:
    """Verifies _normalize_watermark_datetime gracefully handles sentinels and unparseable values."""
    assert _normalize_watermark_datetime(None) is None
    assert _normalize_watermark_datetime("") is None
    assert _normalize_watermark_datetime("   ") is None
    assert _normalize_watermark_datetime("None") is None
    assert _normalize_watermark_datetime("null") is None
    assert _normalize_watermark_datetime("undefined") is None
    assert _normalize_watermark_datetime("N/A") is None
    assert _normalize_watermark_datetime("invalid-date-string") is None

    # Normalization of date and datetime
    d = date(2026, 9, 28)
    dt_res = _normalize_watermark_datetime(d)
    assert dt_res == datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc)

    dt_aware = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    assert _normalize_watermark_datetime(dt_aware) == dt_aware


def test_extract_compact_transcript_prior_context_turns_none(tmp_path: Path) -> None:
    """Verifies prior_context_turns=None falls back to default bound without raising TypeError."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": i,
                "created_at": f"2026-09-2{i:01d}T10:00:00Z",
                "content": f"Turn {i}",
            }
        )
        for i in range(6)
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    # Watermark after turn 4 (so turns 0, 1, 2, 3, 4 are historical)
    compact = extract_compact_transcript(
        transcript_file,
        watermark="2026-09-24T12:00:00Z",
        prior_context_turns=None,  # type: ignore[arg-type]
    )
    # Default is 4 prior turns, so out of 5 historical turns (0..4), only 4 remain (1..4)
    assert len(compact.prior_context) == 4
    assert [t.step_index for t in compact.prior_context] == [1, 2, 3, 4]
    assert len(compact.new_activity) == 1
    assert compact.new_activity[0].step_index == 5


def test_compact_transcript_turns_none_and_compact_turn_goals_none() -> None:
    """Verifies CompactTranscript and CompactTurn defensively normalize None collections."""
    c = CompactTranscript(
        conversation_id="conv-none",
        user_prompts=[],
        agent_thoughts=[],
        planner_goals=[],
        tool_summaries=[],
        turns=None,  # type: ignore[arg-type]
    )
    assert c.turns == []
    assert c.prior_context == []
    assert c.new_activity == []

    t = CompactTurn(turn_type=None, goals=None, tool_summaries=None)  # type: ignore[arg-type]
    assert t.goals == []
    assert t.tool_summaries == []
    assert t.turn_type is None

    # Markdown rendering should not crash on turn_type=None
    md = _render_turn_markdown(t)
    assert "#### [Undated] Agent" in md


def test_render_turn_markdown_clean_goals_and_tools() -> None:
    """Verifies _render_turn_markdown filters empty/None goals and formats multi-line targets."""
    t = CompactTurn(
        step_index=0,
        created_at="2026-09-28T12:00:00Z",
        turn_type="agent",
        content="Testing clean output.",
        is_new=True,
        goals=["", None, "Valid goal", "   "],  # type: ignore[list-item]
        tool_summaries=[
            None,  # type: ignore[list-item]
            {
                "tool": "run_command",
                "toolAction": "Execute\nscript",
                "target": 'python -c "import os\nprint(1)"',
            },
        ],
    )
    md = _render_turn_markdown(t)
    assert "- Valid goal" in md
    assert "- None" not in md
    assert "- ``" not in md
    assert '- `run_command`: Execute script (python -c "import os print(1)")' in md


def test_extract_turn_timestamp_created_at_and_date_in_metadata(tmp_path: Path) -> None:
    """Verifies timestamp extraction handles created_at, Date, stringified JSON metadata, and raw ISO."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "content": "<USER_REQUEST>Req 0</USER_REQUEST>\n<ADDITIONAL_METADATA>\ncreated_at: 2026-09-21T09:00:00Z\n</ADDITIONAL_METADATA>",
            }
        ),
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 1,
                "content": "<USER_REQUEST>Req 1</USER_REQUEST>\n<ADDITIONAL_METADATA>\nDate: 2026-09-21T10:00:00Z.\n</ADDITIONAL_METADATA>",
            }
        ),
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 2,
                "metadata": json.dumps({"created_at": "2026-09-25T11:00:00Z"}),
                "content": "Req 2 with stringified JSON metadata",
            }
        ),
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 3,
                "content": "<USER_REQUEST>Req 3</USER_REQUEST>\n<ADDITIONAL_METADATA>\n2026-09-25T12:00:00Z\n</ADDITIONAL_METADATA>",
            }
        ),
    ]
    transcript_file.write_text("\n".join(lines), encoding="utf-8")

    compact = extract_compact_transcript(
        transcript_file, watermark="2026-09-22T00:00:00Z"
    )
    assert len(compact.prior_context) == 2
    assert compact.turns[0].created_at == "2026-09-21T09:00:00Z"
    assert compact.turns[1].created_at == "2026-09-21T10:00:00Z"

    assert len(compact.new_activity) == 2
    assert compact.turns[2].created_at == "2026-09-25T11:00:00Z"
    assert compact.turns[3].created_at == "2026-09-25T12:00:00Z"


def test_extract_tool_summary_mcp_extended_targets() -> None:
    """Verifies _extract_tool_summary extracts targets for common MCP tools."""
    tc_dir = {
        "name": "list_dir",
        "args": {
            "DirectoryPath": "C:/Users/Steve/project",
            "toolAction": "Listing dir",
        },
    }
    s_dir = _extract_tool_summary(tc_dir, "DONE")
    assert s_dir["target"] == "C:/Users/Steve/project"

    tc_url = {
        "name": "read_url_content",
        "args": {"Url": "https://example.com/api", "toolSummary": "Fetch API docs"},
    }
    s_url = _extract_tool_summary(tc_url, "DONE")
    assert s_url["target"] == "https://example.com/api"

    tc_find = {
        "name": "find_by_name",
        "args": {"Pattern": "*.py", "toolSummary": "Find py files"},
    }
    s_find = _extract_tool_summary(tc_find, "DONE")
    assert s_find["target"] == "*.py"

    tc_nb = {
        "name": "notebook_edit",
        "args": {"NotebookPath": "analysis.ipynb", "toolAction": "Editing cell"},
    }
    s_nb = _extract_tool_summary(tc_nb, "DONE")
    assert s_nb["target"] == "analysis.ipynb"

    tc_web = {
        "name": "search_web",
        "args": {"query": "python 3.12 features", "toolAction": "Web search"},
    }
    s_web = _extract_tool_summary(tc_web, "DONE")
    assert s_web["target"] == "python 3.12 features"


def test_parse_iso_datetime_numeric_and_string_epoch() -> None:
    """Verifies _parse_iso_datetime handles integer, float, and string epoch timestamps."""
    # 1727525515 seconds is 2024-09-28 12:11:55 UTC
    expected = datetime(2024, 9, 28, 12, 11, 55, tzinfo=timezone.utc)

    dt_int = _parse_iso_datetime(1727525515)
    assert dt_int == expected

    dt_str = _parse_iso_datetime("1727525515")
    assert dt_str == expected

    # Milliseconds epoch
    dt_ms = _parse_iso_datetime(1727525515000)
    assert dt_ms == expected

    dt_ms_str = _parse_iso_datetime("1727525515000")
    assert dt_ms_str == expected


def test_build_root_sessions_query_sentinels() -> None:
    """Verifies _build_root_sessions_query does not add last_modified_time filter for sentinels."""
    q_none, p_none = _build_root_sessions_query(
        since="None", exclude_running=True, min_step_count=1
    )
    assert "last_modified_time > ?" not in q_none
    assert "None" not in p_none

    q_null, _ = _build_root_sessions_query(
        since="null", exclude_running=True, min_step_count=1
    )
    assert "last_modified_time > ?" not in q_null

    q_empty, _ = _build_root_sessions_query(
        since="   ", exclude_running=True, min_step_count=1
    )
    assert "last_modified_time > ?" not in q_empty


def test_clean_user_prompt_case_insensitive() -> None:
    """Verifies clean_user_prompt strips lowercase XML metadata tags."""
    raw = (
        "<user_request>Clean prompt text</user_request>\n"
        "<additional_metadata>some meta</additional_metadata>\n"
        "<context_boundary>context</context_boundary>"
    )
    cleaned = clean_user_prompt(raw)
    assert cleaned == "Clean prompt text"


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
