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

"""Pytest fixtures and test mock factories for agy-dreamer."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def mock_db_path(tmp_path: Path) -> Path:
    """Creates a temporary SQLite database mimicking conversation_summaries.db."""
    db_file = tmp_path / "mock_conversation_summaries.db"
    conn = sqlite3.connect(str(db_file))
    try:
        conn.execute("PRAGMA journal_mode = wal;")
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
                battle_id TEXT NOT NULL DEFAULT "",
                winning_conversation_id TEXT NOT NULL DEFAULT "",
                not_fully_idle NUMERIC NOT NULL DEFAULT 0,
                killed NUMERIC NOT NULL DEFAULT 0,
                last_user_input_time DATETIME NOT NULL,
                last_user_input_step_index INTEGER NOT NULL DEFAULT -1,
                app_data_dir TEXT NOT NULL DEFAULT "",
                raw_summary BLOB,
                group_id TEXT NOT NULL DEFAULT ""
            );
            """
        )
        conn.execute(
            """
            CREATE INDEX idx_conversation_summaries_last_modified_time
            ON conversation_summaries (last_modified_time);
            """
        )

        test_rows = [
            (
                "root-session-1",
                "Service Dispatch",
                "Initial service dispatch",
                50,
                "2026-09-25 10:00:00.0000000+00:00",
                '["file:///c%3A/Projects/service-dispatch"]',
                "CASCADE_RUN_STATUS_IDLE",
                0,
                "",
                "2026-09-25 09:59:00.0000000+00:00",
            ),
            (
                "root-session-2",
                "Unanchored System Discussion",
                "Discussing domain concepts and ideas",
                80,
                "2026-09-26 12:00:00.0000000+00:00",
                "",
                "CASCADE_RUN_STATUS_IDLE",
                0,
                "",
                "2026-09-26 11:50:00.0000000+00:00",
            ),
            (
                "root-session-3",
                "Active Running Session",
                "Still actively executing...",
                25,
                "2026-09-27 15:00:00.0000000+00:00",
                '["file:///c%3A/Projects/sample-pipeline"]',
                "CASCADE_RUN_STATUS_RUNNING",
                0,
                "",
                "2026-09-27 14:55:00.0000000+00:00",
            ),
            (
                "root-session-4",
                "Empty Shell Session",
                "",
                0,
                "2026-09-27 16:00:00.0000000+00:00",
                "",
                "CASCADE_RUN_STATUS_IDLE",
                0,
                "",
                "2026-09-27 16:00:00.0000000+00:00",
            ),
            (
                "subagent-depth-1",
                "Subagent Spec Miner",
                "Mining requirements",
                15,
                "2026-09-27 10:30:00.0000000+00:00",
                "",
                "CASCADE_RUN_STATUS_IDLE",
                1,
                "root-session-1",
                "2026-09-27 10:29:00.0000000+00:00",
            ),
            (
                "subagent-depth-2",
                "Nested Subagent Worker",
                "Deeper subagent work",
                5,
                "2026-09-27 11:00:00.0000000+00:00",
                "",
                "CASCADE_RUN_STATUS_IDLE",
                2,
                "subagent-depth-1",
                "2026-09-27 10:59:00.0000000+00:00",
            ),
        ]

        conn.executemany(
            """
            INSERT INTO conversation_summaries (
                conversation_id, title, preview, step_count, last_modified_time,
                workspace_uris, status, nesting_depth, parent_conversation_id,
                last_user_input_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            test_rows,
        )
        conn.commit()
    finally:
        conn.close()

    return db_file


@pytest.fixture
def mock_brain_dir(tmp_path: Path) -> Path:
    """Creates a mock brain directory tree containing various transcript logs."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir(parents=True, exist_ok=True)

    # 1. Normal session with prompts, thinking, tool calls, and large GENERIC output
    session_1_logs = brain_dir / "root-session-1" / ".system_generated" / "logs"
    session_1_logs.mkdir(parents=True, exist_ok=True)
    transcript_1 = session_1_logs / "transcript.jsonl"

    lines_session_1 = [
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 0,
                "content": (
                    "<USER_REQUEST>\n"
                    "Implement the service router contract for ServiceDispatch.\n"
                    "</USER_REQUEST>\n"
                    "<ADDITIONAL_METADATA>\ntime: 2026-09-25\n</ADDITIONAL_METADATA>"
                ),
            }
        ),
        json.dumps(
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 1,
                "thinking": "Need to establish protocol contracts and router interface.",
                "plan": [
                    "Define Router Protocol",
                    "Implement strict payload validator",
                ],
                "tool_calls": [
                    {
                        "name": "write_to_file",
                        "args": {
                            "TargetFile": "C:\\Projects\\service-dispatch\\router.py",
                            "toolAction": "Writing router file",
                            "toolSummary": "Write service router",
                            "CodeContent": "class ServiceRouter:\n    pass\n" * 50,
                        },
                    }
                ],
                "status": "DONE",
            }
        ),
        json.dumps(
            {
                "type": "GENERIC",
                "step_index": 1,
                "status": "DONE",
                "content": "Simulated multi-megabyte stdout: " + ("ABCDE" * 50000),
            }
        ),
        json.dumps(
            {
                "type": "USER_INPUT",
                "step_index": 2,
                "content": (
                    "Also ensure no backwards compatibility shims are added.\n"
                    "<USER_SETTINGS_CHANGE>auto_commit=true</USER_SETTINGS_CHANGE>"
                ),
            }
        ),
        json.dumps(
            {
                "type": "PLANNER_RESPONSE",
                "step_index": 3,
                "thinking": "Understood. Removing all shims and ensuring strict models.",
                "tool_calls": [
                    {
                        "name": "run_command",
                        "args": {
                            "CommandLine": "pytest tests/test_router.py",
                            "toolAction": "Running tests",
                            "toolSummary": "Run test suite",
                        },
                    }
                ],
                "status": "DONE",
            }
        ),
    ]
    transcript_1.write_text("\n".join(lines_session_1) + "\n", encoding="utf-8")

    # 2. Corrupted transcript with malformed JSON and empty lines
    session_corr_logs = (
        brain_dir / "root-session-corrupted" / ".system_generated" / "logs"
    )
    session_corr_logs.mkdir(parents=True, exist_ok=True)
    transcript_corr = session_corr_logs / "transcript.jsonl"
    lines_corr = [
        "",
        '{"type": "USER_INPUT", "content": "<USER_REQUEST>Fix bug</USER_REQUEST>"}',
        "THIS_IS_NOT_VALID_JSON{[[",
        '{"type": "PLANNER_RESPONSE", "thinking": "Investigating...", "tool_calls": null}',
        "",
    ]
    transcript_corr.write_text("\n".join(lines_corr) + "\n", encoding="utf-8")

    # 3. Large payload session (simulated 3 MB tool output)
    session_large_logs = brain_dir / "root-session-large" / ".system_generated" / "logs"
    session_large_logs.mkdir(parents=True, exist_ok=True)
    transcript_large = session_large_logs / "transcript.jsonl"
    lines_large = [
        json.dumps(
            {
                "type": "USER_INPUT",
                "content": "<USER_REQUEST>Large session prompt</USER_REQUEST>",
            }
        ),
        json.dumps(
            {
                "type": "PLANNER_RESPONSE",
                "thinking": "Analyzing large trace.",
                "tool_calls": [
                    {
                        "name": "run_command",
                        "args": {
                            "CommandLine": "python analyze.py",
                            "toolAction": "Running analysis",
                            "toolSummary": "Run analyzer",
                        },
                    }
                ],
            }
        ),
        json.dumps(
            {
                "type": "GENERIC",
                "status": "DONE",
                "content": "Z" * (3 * 1024 * 1024),  # 3 MB string
            }
        ),
    ]
    transcript_large.write_text("\n".join(lines_large) + "\n", encoding="utf-8")

    # 4. Empty transcript session
    session_empty_logs = brain_dir / "root-session-empty" / ".system_generated" / "logs"
    session_empty_logs.mkdir(parents=True, exist_ok=True)
    (session_empty_logs / "transcript.jsonl").write_text("", encoding="utf-8")

    return brain_dir


@pytest.fixture
def mock_memory_dir(tmp_path: Path) -> Path:
    """Creates a mock memory directory structure with active and archived files."""
    mem_dir = tmp_path / "memory"
    (mem_dir / "core").mkdir(parents=True, exist_ok=True)
    (mem_dir / "projects").mkdir(parents=True, exist_ok=True)
    (mem_dir / "domains").mkdir(parents=True, exist_ok=True)
    (mem_dir / "people").mkdir(parents=True, exist_ok=True)
    (mem_dir / "archive").mkdir(parents=True, exist_ok=True)
    (mem_dir / "proposals").mkdir(parents=True, exist_ok=True)

    # Core files
    (mem_dir / "core" / "preferences.md").write_text(
        "# Preferences\nDirect concise style.\n", encoding="utf-8"
    )
    (mem_dir / "core" / "guardrails.md").write_text(
        "# Guardrails\nNever restart HA.\n", encoding="utf-8"
    )

    # Project file with multiple Keyed Invariants
    sample_project_content = """# Sample Project Invariants

<!-- INVARIANT_KEY: sample_project.contour_integrity -->
<!-- LAST_CONFIRMED: 2026-09-27 (Session: 5b184a03) -->
<!-- SUPERSEDES: sample_project.old_contour -->
- **Target**: `GeometryModel` polygon contour modeling
  **Invariant**: Contour and mask must be genuine multi-point polygons.
  **Negative Constraint**: Rectangular bounding boxes and legacy shims are strictly forbidden.
  **Rationale**: Downstream CV spatial perception requires true geometric centroids.

<!-- INVARIANT_KEY: sample_project.model_runtime -->
<!-- LAST_CONFIRMED: 2026-09-26 (Session: 1a2b3c4d) -->
- **Target**: Neural model execution
  **Invariant**: All model weights execute in GPU fp16 memory.
  **Negative Constraint**: Never fall back to CPU emulation in production pipelines.
  **Rationale**: CPU fallback causes throughput starvation.
"""
    (mem_dir / "projects" / "sample-project.md").write_text(
        sample_project_content, encoding="utf-8"
    )

    # Domain file with single invariant
    cloud_infra_content = """# Cloud Infrastructure Domain Invariants

<!-- INVARIANT_KEY: cloud_infra.service_uptime_rule -->
<!-- LAST_CONFIRMED: 2026-09-20 (Session: e9f8d7c6) -->
- **Target**: Core Service Host
  **Invariant**: Core service must maintain continuous uptime during automated checks.
  **Negative Constraint**: NEVER restart core service without explicit express permission.
  **Rationale**: Restarts disrupt ongoing automations and service connectivity.
"""
    (mem_dir / "domains" / "cloud-infra.md").write_text(
        cloud_infra_content, encoding="utf-8"
    )

    # Archive file (should be excluded from active files list)
    (mem_dir / "archive" / "superseded.md").write_text(
        "# Superseded Invariants\n<!-- INVARIANT_KEY: sample_project.old_contour -->\n",
        encoding="utf-8",
    )

    # Proposals file
    (mem_dir / "proposals" / "2026-09-28.md").write_text(
        "# Candidate Invariant Proposals\n", encoding="utf-8"
    )

    return mem_dir


@pytest.fixture
def mock_state_file(tmp_path: Path) -> Path:
    """Creates a temporary .state.json file."""
    state_file = tmp_path / "memory" / ".state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    initial_data = {
        "version": 1,
        "cold_start_completed": True,
        "cold_start_timestamp": "2026-09-25T00:00:00Z",
        "last_dream_timestamp": "2026-09-26T03:00:00Z",
        "watermark_last_modified_time": "2026-09-26 12:00:00.0000000+00:00",
        "last_consolidated_timestamp": "2026-09-26 12:00:00.0000000+00:00",
        "last_consolidated_session_id": "root-session-2",
        "processed_session_ids": ["root-session-1", "root-session-2"],
        "last_run_mode": "turbo",
        "stats": {
            "total_root_sessions_scanned": 2,
            "total_invariants_extracted": 3,
            "total_proposals_staged": 0,
            "total_invariants_auto_committed": 3,
            "total_superseded_invariants": 1,
        },
    }
    state_file.write_text(json.dumps(initial_data, indent=2), encoding="utf-8")
    return state_file
