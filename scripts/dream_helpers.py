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

"""Deterministic helper engine and transcript parsing utilities for agy-dreamer.

Provides safe, read-only SQLite querying for root sessions in Antigravity,
high-throughput streaming extraction and payload compaction for transcript logs,
atomic state management for memory consolidation watermarks, and invariant
manifest scanning.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# ============================================================================
# Top-Level Constants & Default Paths
# ============================================================================

_DEFAULT_BUSY_TIMEOUT_MS: int = 5000
_DEFAULT_MAX_THOUGHT_CHARS: int = 2000
_DEFAULT_MIN_STEP_COUNT: int = 1
_DEFAULT_PRIOR_CONTEXT_TURNS: int = 4
_RUNNING_STATUS: str = "CASCADE_RUN_STATUS_RUNNING"

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH: Path = (
    Path.home() / ".gemini" / "antigravity" / "conversation_summaries.db"
)
DEFAULT_BRAIN_DIR: Path = Path.home() / ".gemini" / "antigravity" / "brain"
DEFAULT_STATE_FILE: Path = (
    Path.home() / ".gemini" / "config" / "dreaming" / ".state.json"
)


# ============================================================================
# Core Data Models
# ============================================================================


@dataclass
class SessionSummary:
    """Metadata summary of a conversation session from SQLite.

    Attributes:
        conversation_id: Unique UUID of the conversation session.
        title: Human-readable session title or user query summary.
        preview: First-turn preview text of the conversation.
        last_modified_time: Last activity timestamp as a timezone-aware datetime.
        workspace_uris: List of file URIs associated with the session.
        step_count: Number of conversational or tool execution steps.
        status: Execution status (e.g. CASCADE_RUN_STATUS_IDLE, CASCADE_RUN_STATUS_RUNNING).
        nesting_depth: Depth in the agent delegation tree (0 = user root session).
        parent_conversation_id: UUID of parent session if this is a subagent.
        last_user_input_time: Timestamp of the most recent user turn.
    """

    conversation_id: str
    title: str
    preview: str
    last_modified_time: datetime
    workspace_uris: list[str]
    step_count: int
    status: str = ""
    nesting_depth: int = 0
    parent_conversation_id: str = ""
    last_user_input_time: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.last_modified_time, str):
            object.__setattr__(
                self,
                "last_modified_time",
                _parse_iso_datetime(self.last_modified_time),
            )


@dataclass
class CompactTurn:
    """Represents an individual conversational turn in a compact transcript.

    Attributes:
        step_index: Integer turn or execution step index within the session.
        created_at: Literal ISO timestamp string of the turn (empty if missing).
        turn_type: Role or type of turn ('user' or 'agent').
        content: Cleaned user prompt or trimmed agent thought/message.
        is_new: True if turn occurred strictly after watermark; False if prior context.
        goals: List of high-level planner goals formulated during this turn.
        tool_summaries: Compact metadata dictionaries of tool calls executed in this turn.
    """

    step_index: int = 0
    created_at: str = ""
    turn_type: str = "user"
    content: str = ""
    is_new: bool = True
    goals: list[str] = field(default_factory=list)
    tool_summaries: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.goals is None:
            object.__setattr__(self, "goals", [])
        if self.tool_summaries is None:
            object.__setattr__(self, "tool_summaries", [])

    def to_dict(self) -> dict[str, Any]:
        """Serializes the turn to a dictionary."""
        return asdict(self)


@dataclass
class CompactTranscript:
    """Compact representation of an extracted conversation transcript.

    Attributes:
        conversation_id: UUID of the session.
        user_prompts: Cleaned prompts submitted by the user.
        agent_thoughts: Trimmed internal thoughts and reasoning from planner turns.
        planner_goals: Goals and high-level plans discovered during execution.
        tool_summaries: Compact metadata dictionaries for tool invocations.
        turns: Ordered list of CompactTurn models representing individual turns.
    """

    conversation_id: str
    user_prompts: list[str]
    agent_thoughts: list[str]
    planner_goals: list[str]
    tool_summaries: list[dict[str, str]]
    turns: list[CompactTurn] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.turns is None:
            object.__setattr__(self, "turns", [])

    @property
    def prior_context(self) -> list[CompactTurn]:
        """Turns categorized as prior context (created_at <= watermark)."""
        if not self.turns:
            return []
        return [t for t in self.turns if not t.is_new]

    @property
    def new_activity(self) -> list[CompactTurn]:
        """Turns categorized as new activity (created_at > watermark)."""
        if self.turns:
            return [t for t in self.turns if t.is_new]
        synthesized: list[CompactTurn] = []
        idx = 0
        for p in self.user_prompts:
            synthesized.append(
                CompactTurn(
                    step_index=idx,
                    turn_type="user",
                    content=p,
                    is_new=True,
                )
            )
            idx += 1
        for t in self.agent_thoughts:
            synthesized.append(
                CompactTurn(
                    step_index=idx,
                    turn_type="agent",
                    content=t,
                    is_new=True,
                )
            )
            idx += 1
        if (self.planner_goals or self.tool_summaries) and not self.agent_thoughts:
            synthesized.append(
                CompactTurn(
                    step_index=idx,
                    turn_type="agent",
                    content="",
                    is_new=True,
                    goals=list(self.planner_goals),
                    tool_summaries=list(self.tool_summaries),
                )
            )
        elif (self.planner_goals or self.tool_summaries) and synthesized:
            last_agent = next(
                (t for t in reversed(synthesized) if t.turn_type == "agent"), None
            )
            if last_agent:
                last_agent.goals = list(self.planner_goals)
                last_agent.tool_summaries = list(self.tool_summaries)
        return synthesized

    def to_dict(self) -> dict[str, Any]:
        """Serializes the compact transcript to a dictionary."""
        return asdict(self)

    def render_partitioned_markdown(self) -> str:
        """Renders transcript into partitioned Markdown with timestamps and section headers."""
        return _render_transcript_partitioned_markdown(self)


def _render_transcript_partitioned_markdown(transcript: CompactTranscript) -> str:
    """Renders partitioned Markdown with explicit timestamps and section headers."""
    sections: list[str] = []

    sections.append("### Prior Context")
    if transcript.prior_context:
        for turn in transcript.prior_context:
            sections.append("")
            sections.append(_render_turn_markdown(turn))
    else:
        sections.append("")
        sections.append("*(No prior context)*")

    sections.append("")

    sections.append("### New Activity")
    if transcript.new_activity:
        for turn in transcript.new_activity:
            sections.append("")
            sections.append(_render_turn_markdown(turn))
    else:
        sections.append("")
        sections.append("*(No new activity)*")

    return "\n".join(sections).strip()


def _render_turn_markdown(turn: CompactTurn) -> str:
    """Renders a single compact turn as structured Markdown with [YYYY-MM-DD HH:MM]."""
    ts = _format_turn_timestamp(turn.created_at)
    turn_type_str = str(turn.turn_type or "").lower()
    is_user = turn_type_str in ("user", "user_input")
    role_label = "User" if is_user else "Agent"

    lines: list[str] = [f"#### {ts} {role_label}"]

    content = str(turn.content or "").strip()
    if content:
        lines.append("")
        lines.append(content)

    if turn.goals:
        clean_goals = [str(g).strip() for g in turn.goals if g and str(g).strip()]
        if clean_goals:
            lines.append("")
            lines.append("**Goals:**")
            for goal in clean_goals:
                lines.append(f"- {goal}")

    if turn.tool_summaries:
        valid_tools = [t for t in turn.tool_summaries if t]
        if valid_tools:
            lines.append("")
            lines.append("**Tools:**")
            for tool in valid_tools:
                lines.append(_render_tool_summary_line(tool))

    return "\n".join(lines)


def _render_tool_summary_line(tool_dict: dict[str, str] | Any) -> str:
    """Formats a tool summary entry as a compact bullet point."""
    if not isinstance(tool_dict, dict):
        return f"- `{tool_dict}`"
    tool_name = str(tool_dict.get("tool") or "tool").strip()
    raw_summary = (
        tool_dict.get("summary")
        or tool_dict.get("toolSummary")
        or tool_dict.get("action")
        or tool_dict.get("toolAction")
        or ""
    )
    summary = " ".join(str(raw_summary).split())
    raw_target = tool_dict.get("target") or ""
    target = " ".join(str(raw_target).split())
    if summary and target:
        return f"- `{tool_name}`: {summary} ({target})"
    if summary:
        return f"- `{tool_name}`: {summary}"
    if target:
        return f"- `{tool_name}`: {target}"
    return f"- `{tool_name}`"


def _format_turn_timestamp(created_at: str | datetime | date | None) -> str:
    """Formats turn timestamp string into [YYYY-MM-DD HH:MM] representation."""
    if not created_at or not str(created_at).strip():
        return "[Undated]"
    try:
        dt = _parse_iso_datetime(created_at)
        if dt == datetime.min.replace(tzinfo=timezone.utc):
            return "[Undated]"
        return f"[{dt.strftime('%Y-%m-%d %H:%M')}]"
    except (ValueError, TypeError):
        clean = str(created_at).strip().strip("[]\"'")
        return f"[{clean}]"


@dataclass
class DreamState:
    """Persistent watermark and consolidation state for agy-dreamer.

    Attributes:
        cold_start_completed: Whether historical sessions have been bootstrapped.
        last_consolidated_timestamp: High-water mark ISO timestamp of consolidated sessions.
        last_consolidated_session_id: ID of the last consolidated root session.
        processed_session_ids: Set/list of historical root session IDs already ingested.
        schema_version: State schema version number.
        cold_start_timestamp: Timestamp when cold start bootstrapping completed.
        last_dream_timestamp: Timestamp of the most recent incremental dream cycle.
        watermark_last_modified_time: Alias for last_consolidated_timestamp.
        last_run_mode: Execution mode ('turbo' or 'standard').
        stats: Aggregated metrics tracking extraction counts.
    """

    cold_start_completed: bool = False
    last_consolidated_timestamp: str = ""
    last_consolidated_session_id: str = ""
    processed_session_ids: list[str] = field(default_factory=list)
    schema_version: int = 1
    cold_start_timestamp: str | None = None
    last_dream_timestamp: str | None = None
    watermark_last_modified_time: str | None = None
    last_run_mode: str = "turbo"
    stats: dict[str, int] = field(
        default_factory=lambda: {
            "total_root_sessions_scanned": 0,
            "total_invariants_extracted": 0,
            "total_proposals_staged": 0,
            "total_invariants_auto_committed": 0,
            "total_superseded_invariants": 0,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        """Serializes the state object to a dictionary."""
        return asdict(self)


@dataclass
class KeyedInvariant:
    """A durable architectural invariant extracted from sessions.

    Attributes:
        key: Unique dot-delimited key (e.g. 'sample_project.feature_invariance').
        last_confirmed: Human-readable or ISO timestamp/session confirmation string.
        supersedes: Previous invariant key this rule replaces, or None.
        target: Target component, module, or architecture boundary.
        invariant: Unconditional affirmative invariant requirement.
        negative_constraint: Explicit anti-pattern or prohibited behavior.
        rationale: Operational or architectural justification for the rule.
        file_path: Source memory file path containing the invariant block.
    """

    key: str
    last_confirmed: str
    supersedes: str | None
    target: str
    invariant: str
    negative_constraint: str
    rationale: str
    file_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serializes the invariant to a dictionary."""
        return asdict(self)


# ============================================================================
# Category A: SQLite Database Operations
# ============================================================================


def get_readonly_connection(
    db_path: str | Path = DEFAULT_DB_PATH,
    timeout_ms: int = _DEFAULT_BUSY_TIMEOUT_MS,
) -> sqlite3.Connection:
    """Opens a safe, read-only SQLite connection in WAL mode with a busy timeout.

    Enforces URI read-only mode (?mode=ro) to guarantee that background queries
    never hold exclusive write locks or corrupt the active Antigravity session
    database.

    Args:
        db_path: Path to the SQLite database file or ':memory:'.
        timeout_ms: Busy timeout in milliseconds to handle active writer contention.

    Returns:
        A sqlite3.Connection configured with row_factory=sqlite3.Row.

    Raises:
        FileNotFoundError: If the specified db_path does not exist on disk.
        sqlite3.OperationalError: If connection fails or violates read-only mode.
    """
    if str(db_path) == ":memory:":
        conn = sqlite3.connect(":memory:", timeout=timeout_ms / 1000.0)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {int(timeout_ms)};")
        return conn

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"Database file not found: {path}")

    uri = _build_sqlite_ro_uri(path)
    conn = sqlite3.connect(uri, uri=True, timeout=timeout_ms / 1000.0)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(timeout_ms)};")
    return conn


def _build_sqlite_ro_uri(file_path: Path) -> str:
    """Builds a URI string with ?mode=ro for safe SQLite connections."""
    resolved_uri = file_path.resolve().as_uri()
    return f"{resolved_uri}?mode=ro"


def query_root_sessions(
    since: datetime | str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
    exclude_running: bool = True,
    min_step_count: int = _DEFAULT_MIN_STEP_COUNT,
) -> list[SessionSummary]:
    """Queries conversation_summaries.db for user root sessions (nesting_depth == 0).

    Uses the idx_conversation_summaries_last_modified_time index when a watermark
    timestamp is specified. Safely parses workspace URIs and filters out
    subagent delegations and empty session shells.

    Args:
        since: Optional cutoff timestamp; only sessions modified after this are returned.
        db_path: Path to conversation_summaries.db or a mock test database.
        exclude_running: When True, filters out active CASCADE_RUN_STATUS_RUNNING sessions.
        min_step_count: Minimum step count required (default 1 excludes 0-step shells).

    Returns:
        List of SessionSummary objects ordered chronologically by last_modified_time ASC.
    """
    # Defensive parameter swap: handle callers who pass db_path positionally first
    if isinstance(since, Path) or (
        isinstance(since, str)
        and (Path(since).is_file() or since.endswith((".db", ".sqlite", ".sqlite3")))
    ):
        actual_db_path = since
        actual_since = None
    else:
        actual_db_path = db_path
        actual_since = since

    conn = get_readonly_connection(actual_db_path)
    try:
        query_sql, params = _build_root_sessions_query(
            since=actual_since,
            exclude_running=exclude_running,
            min_step_count=min_step_count,
        )
        cursor = conn.execute(query_sql, params)
        return [_row_to_session_summary(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def _build_root_sessions_query(
    since: datetime | str | None,
    exclude_running: bool,
    min_step_count: int,
) -> tuple[str, list[Any]]:
    """Builds parameterized SQL query and arguments for root session extraction."""
    clauses = ["nesting_depth = 0"]
    params: list[Any] = []

    if min_step_count > 0:
        clauses.append("step_count >= ?")
        params.append(min_step_count)

    if exclude_running:
        clauses.append("status != ?")
        params.append(_RUNNING_STATUS)

    if since is not None:
        clean_since = str(since).strip()
        if clean_since and clean_since.lower() not in (
            "none",
            "null",
            "undefined",
            "n/a",
        ):
            clauses.append("last_modified_time > ?")
            params.append(_format_datetime_for_sqlite(since))

    where_expr = " AND ".join(clauses)
    query = (
        "SELECT conversation_id, title, preview, step_count, last_modified_time, "
        "workspace_uris, status, nesting_depth, parent_conversation_id, last_user_input_time "
        f"FROM conversation_summaries WHERE {where_expr} "
        "ORDER BY last_modified_time ASC"
    )
    return query, params


def _row_to_session_summary(row: sqlite3.Row) -> SessionSummary:
    """Transforms a SQLite database row into a strongly-typed SessionSummary."""
    raw_uris = str(row["workspace_uris"] or "")
    return SessionSummary(
        conversation_id=str(row["conversation_id"]),
        title=str(row["title"] or ""),
        preview=str(row["preview"] or ""),
        last_modified_time=_parse_iso_datetime(row["last_modified_time"]),
        workspace_uris=parse_workspace_uris(raw_uris),
        step_count=int(row["step_count"] or 0),
        status=str(row["status"] or ""),
        nesting_depth=int(row["nesting_depth"] or 0),
        parent_conversation_id=str(row["parent_conversation_id"] or ""),
        last_user_input_time=str(row["last_user_input_time"] or ""),
    )


def get_session_by_id(
    conversation_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> SessionSummary | None:
    """Fetches a single session summary by conversation UUID.

    Args:
        conversation_id: The UUID of the conversation session.
        db_path: Path to the SQLite database.

    Returns:
        SessionSummary if found, or None if no record matches.
    """
    conn = get_readonly_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT conversation_id, title, preview, step_count, last_modified_time, "
            "workspace_uris, status, nesting_depth, parent_conversation_id, last_user_input_time "
            "FROM conversation_summaries WHERE conversation_id = ? LIMIT 1",
            (conversation_id,),
        )
        row = cursor.fetchone()
        return _row_to_session_summary(row) if row else None
    finally:
        conn.close()


def _parse_iso_datetime(val: str | datetime | date | float) -> datetime:
    """Parses SQLite datetime string, epoch timestamp, or normalizes datetime/date object.

    Handles ISO formats with spaces, 'T', and 7-digit subsecond precision.
    Guarantees returned datetime is timezone-aware (UTC).
    """
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(val, (int, float)):
        ts = float(val)
        if ts > 1e11:  # Milliseconds
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    clean_str = str(val).strip().strip("[]\"'")
    if not clean_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    if re.match(r"^\d{10,13}(?:\.\d+)?$", clean_str):
        ts = float(clean_str)
        if ts > 1e11:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    if clean_str.endswith(("Z", "z")):
        clean_str = clean_str[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(clean_str)
    except ValueError:
        # Fallback if 7-digit fractional seconds caused parser error on older runtimes
        normalized = re.sub(r"(\.\d{6})\d+", r"\1", clean_str)
        dt = datetime.fromisoformat(normalized)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _format_datetime_for_sqlite(dt_val: datetime | str) -> str:
    """Normalizes datetime to SQLite string representation for index comparison."""
    if isinstance(dt_val, str):
        # Normalize ISO 'T' to space for lexicographical match with SQLite stored strings
        return dt_val.replace("T", " ").strip()
    parsed_dt = _parse_iso_datetime(dt_val)
    return parsed_dt.strftime("%Y-%m-%d %H:%M:%S")


# ============================================================================
# Category B: Workspace URI Normalization
# ============================================================================


def parse_workspace_uris(raw_json: str) -> list[str]:
    """Parses SQLite workspace_uris JSON string into a list of URI strings.

    Defensively handles empty strings, empty arrays, malformed JSON, and
    single-string payloads.

    Args:
        raw_json: JSON string from conversation_summaries.workspace_uris.

    Returns:
        List of URI strings, or an empty list if missing or invalid.
    """
    if not raw_json or not isinstance(raw_json, str):
        return []
    clean_str = raw_json.strip()
    if clean_str in ("", "[]"):
        return []
    try:
        data = json.loads(clean_str)
        if isinstance(data, list):
            return [str(item) for item in data if item]
        if isinstance(data, str) and data.strip():
            return [data.strip()]
        return []
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def uri_to_local_path(uri: str) -> str:
    """Decodes a file URI to a normalized local filesystem path.

    Handles Windows file URIs (e.g., file:///c%3A/Users/... -> C:\\Users\\...)
    as well as standard POSIX file URIs.

    Args:
        uri: The file URI or filesystem path to convert.

    Returns:
        The normalized local filesystem path string.
    """
    if not uri or not isinstance(uri, str):
        return ""
    if not uri.startswith("file:"):
        return os.path.normpath(uri)

    unquoted = urllib.parse.unquote(uri)
    parsed = urllib.parse.urlsplit(unquoted)
    path = urllib.request.url2pathname(parsed.path)
    if len(path) >= 2 and path[1] == ":" and path[0].isalpha():
        path = path[0].upper() + path[1:]
    return os.path.normpath(path)


def extract_project_slug(workspace_uri: str) -> str:
    """Extracts a clean project slug from a workspace URI or local path.

    Args:
        workspace_uri: Workspace URI or local path (e.g. file:///path/to/sample-project).

    Returns:
        Project slug string (e.g. 'sample-project').
    """
    local_path = uri_to_local_path(workspace_uri)
    if not local_path:
        return ""
    return Path(local_path).name


# ============================================================================
# Category C: Transcript Streaming & Payload Compaction
# ============================================================================


def resolve_transcript_path(
    session_id: str,
    brain_dir: str | Path = DEFAULT_BRAIN_DIR,
) -> Path | None:
    """Resolves the transcript.jsonl file path for a session ID.

    Defensively verifies directory and file existence to gracefully handle
    the ~12% of sessions that exist in SQLite but have missing disk folders.

    Args:
        session_id: The UUID or string identifier of the session.
        brain_dir: Path to the root brain storage directory.

    Returns:
        Path to transcript.jsonl if present, or None if missing.
    """
    if not session_id:
        return None
    target = (
        Path(brain_dir) / session_id / ".system_generated" / "logs" / "transcript.jsonl"
    )
    return target if target.is_file() else None


def clean_user_prompt(raw_content: str) -> str:
    """Strips metadata wrapper tags from raw user prompt content.

    Extracts text within <USER_REQUEST>...</USER_REQUEST> if present.
    Otherwise strips <ADDITIONAL_METADATA>, <USER_SETTINGS_CHANGE>,
    and <CONTEXT_BOUNDARY> tags.

    Args:
        raw_content: Raw string from transcript USER_INPUT content.

    Returns:
        Cleaned user prompt string.
    """
    if not raw_content or not isinstance(raw_content, str):
        return ""
    req_match = re.search(
        r"<USER_REQUEST>(.*?)</USER_REQUEST>",
        raw_content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if req_match:
        return req_match.group(1).strip()
    cleaned = re.sub(
        r"<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>",
        "",
        raw_content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    cleaned = re.sub(
        r"<USER_SETTINGS_CHANGE>.*?</USER_SETTINGS_CHANGE>",
        "",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )
    cleaned = re.sub(
        r"<CONTEXT_BOUNDARY>.*?</CONTEXT_BOUNDARY>",
        "",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return cleaned.strip()


def extract_user_prompts(
    session_id: str,
    brain_dir: str | Path = DEFAULT_BRAIN_DIR,
) -> list[str]:
    """Extracts cleaned user prompts from a session's transcript.

    Args:
        session_id: UUID of the conversation session.
        brain_dir: Path to the brain storage directory.

    Returns:
        List of cleaned user prompt strings. Returns empty list if missing.
    """
    transcript_path = resolve_transcript_path(session_id, brain_dir)
    if transcript_path is None:
        return []

    prompts: list[str] = []
    with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue
            try:
                record = json.loads(line_str)
                if record.get("type") == "USER_INPUT":
                    cleaned = clean_user_prompt(record.get("content") or "")
                    if cleaned:
                        prompts.append(cleaned)
            except (json.JSONDecodeError, TypeError):
                continue
    return prompts


def extract_compact_transcript(
    session_id: str | Path,
    brain_dir: str | Path = DEFAULT_BRAIN_DIR,
    max_thought_chars: int = _DEFAULT_MAX_THOUGHT_CHARS,
    raise_on_missing: bool = False,
    watermark: datetime | str | None = None,
    prior_context_turns: int = _DEFAULT_PRIOR_CONTEXT_TURNS,
) -> CompactTranscript:
    """Streams a transcript and extracts high-leverage context while stripping multi-MB payloads.

    Extracts:
    1. USER_INPUT prompts (cleaned).
    2. PLANNER_RESPONSE thoughts (trimmed to max_thought_chars).
    3. High-level planner goals and plan structures.
    4. Compact tool invocation summaries (tool, toolAction, toolSummary, status).
    5. Turn-level CompactTurn models partitioned into Prior Context and New Activity.

    Explicitly discards:
    - GENERIC.content (raw stdout/terminal dumps that often reach 10+ MB).
    - CodeContent, ReplacementContent, TargetContent in tool arguments.

    Args:
        session_id: Session UUID or direct Path to a transcript.jsonl file.
        brain_dir: Root brain directory path.
        max_thought_chars: Character limit for internal thoughts before truncation.
        raise_on_missing: If True, raises FileNotFoundError when transcript is missing.
        watermark: Timestamp boundary (datetime or ISO str). Turns on/before are prior context;
            turns after are new activity. If None, all turns are marked as new activity.
        prior_context_turns: Maximum number of recent historical turns to retain in prior context.

    Returns:
        CompactTranscript object containing structured, compacted session context.

    Raises:
        FileNotFoundError: If raise_on_missing is True and file does not exist.
    """
    transcript_path, cid = _resolve_transcript_or_path(session_id, brain_dir)
    if transcript_path is None or not transcript_path.is_file():
        if raise_on_missing:
            raise FileNotFoundError(f"Transcript not found for session: {cid}")
        return CompactTranscript(
            conversation_id=cid,
            user_prompts=[],
            agent_thoughts=[],
            planner_goals=[],
            tool_summaries=[],
            turns=[],
        )

    return _stream_and_compact_transcript(
        transcript_path=transcript_path,
        conversation_id=cid,
        max_thought_chars=max_thought_chars,
        watermark=watermark,
        prior_context_turns=prior_context_turns,
    )


def _resolve_transcript_or_path(
    session_or_path: str | Path,
    brain_dir: str | Path,
) -> tuple[Path | None, str]:
    """Resolves session identifier or filesystem path to transcript Path and UUID."""
    if isinstance(session_or_path, Path) or (
        isinstance(session_or_path, str)
        and (
            Path(session_or_path).is_file()
            or session_or_path.endswith(".jsonl")
            or "/" in session_or_path
            or "\\" in session_or_path
        )
    ):
        p = Path(session_or_path)
        cid = p.parent.parent.parent.name if p.name == "transcript.jsonl" else p.stem
        return (p if p.is_file() else None), cid

    cid = str(session_or_path)
    return resolve_transcript_path(cid, brain_dir), cid


def _stream_and_compact_transcript(
    transcript_path: Path,
    conversation_id: str,
    max_thought_chars: int,
    watermark: datetime | str | None = None,
    prior_context_turns: int = _DEFAULT_PRIOR_CONTEXT_TURNS,
) -> CompactTranscript:
    """Streams transcript file line-by-line and accumulates compacted records and turns."""
    watermark_dt = _normalize_watermark_datetime(watermark)
    raw_turns: list[CompactTurn] = []
    current_timestamp: str = ""

    with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            clean_line = line.strip()
            if not clean_line:
                continue
            try:
                record = json.loads(clean_line)
            except (json.JSONDecodeError, TypeError):
                continue

            extracted_ts = _extract_turn_timestamp(record)
            if extracted_ts:
                current_timestamp = extracted_ts

            rec_type = record.get("type")
            if rec_type == "USER_INPUT":
                turn = _process_user_record(
                    record=record,
                    watermark_dt=watermark_dt,
                    fallback_timestamp=current_timestamp,
                )
                if turn is not None:
                    raw_turns.append(turn)
            elif rec_type == "PLANNER_RESPONSE":
                turn = _process_planner_turn_record(
                    record=record,
                    max_thought_chars=max_thought_chars,
                    watermark_dt=watermark_dt,
                    fallback_timestamp=current_timestamp,
                )
                if turn is not None:
                    raw_turns.append(turn)

    # Backfill any leading turns that lacked timestamps with the first discovered timestamp
    first_known_ts = next(
        (t.created_at for t in raw_turns if t.created_at and t.created_at.strip()), ""
    )
    if first_known_ts:
        for t in raw_turns:
            if not t.created_at or not t.created_at.strip():
                t.created_at = first_known_ts
                t.is_new = _is_turn_new(first_known_ts, watermark_dt)
            else:
                break

    # Partition into prior context and new activity
    prior_turns = [t for t in raw_turns if not t.is_new]
    new_turns = [t for t in raw_turns if t.is_new]

    # Bound prior context to the most recent prior_context_turns
    effective_prior_turns = (
        _DEFAULT_PRIOR_CONTEXT_TURNS
        if prior_context_turns is None or not isinstance(prior_context_turns, int)
        else prior_context_turns
    )
    bounded_prior: list[CompactTurn] = (
        [] if effective_prior_turns <= 0 else prior_turns[-effective_prior_turns:]
    )
    final_turns = bounded_prior + new_turns

    # Reconstitute aggregate lists for full backward compatibility
    user_prompts: list[str] = []
    agent_thoughts: list[str] = []
    planner_goals: list[str] = []
    tool_summaries: list[dict[str, str]] = []

    for turn in final_turns:
        if turn.turn_type.lower() in ("user", "user_input"):
            if turn.content:
                user_prompts.append(turn.content)
        else:
            if turn.content:
                agent_thoughts.append(turn.content)
            if turn.goals:
                planner_goals.extend(turn.goals)
            if turn.tool_summaries:
                tool_summaries.extend(turn.tool_summaries)

    return CompactTranscript(
        conversation_id=conversation_id,
        user_prompts=user_prompts,
        agent_thoughts=agent_thoughts,
        planner_goals=planner_goals,
        tool_summaries=tool_summaries,
        turns=final_turns,
    )


def _normalize_watermark_datetime(
    watermark: datetime | date | str | float | None,
) -> datetime | None:
    """Normalizes watermark parameter to timezone-aware UTC datetime or None."""
    if watermark is None:
        return None
    if isinstance(watermark, str):
        clean_wm = watermark.strip().lower()
        if not clean_wm or clean_wm in ("none", "null", "undefined", "n/a"):
            return None
    try:
        dt = _parse_iso_datetime(watermark)
        if dt == datetime.min.replace(tzinfo=timezone.utc):
            return None
        return dt
    except (ValueError, TypeError):
        logger.warning("Unparseable watermark value: %r; treating as None.", watermark)
        return None


def _process_user_record(
    record: dict[str, Any],
    watermark_dt: datetime | None,
    fallback_timestamp: str = "",
) -> CompactTurn | None:
    """Processes a USER_INPUT record into a CompactTurn."""
    prompt = clean_user_prompt(record.get("content") or "")
    if not prompt:
        return None

    step_index = _parse_step_index(record.get("step_index"))
    created_at = _extract_turn_timestamp(record) or fallback_timestamp
    is_new = _is_turn_new(created_at, watermark_dt)

    return CompactTurn(
        step_index=step_index,
        created_at=created_at,
        turn_type="user",
        content=prompt,
        is_new=is_new,
        goals=[],
        tool_summaries=[],
    )


def _process_planner_turn_record(
    record: dict[str, Any],
    max_thought_chars: int,
    watermark_dt: datetime | None,
    fallback_timestamp: str = "",
) -> CompactTurn | None:
    """Processes a PLANNER_RESPONSE record into a CompactTurn."""
    step_index = _parse_step_index(record.get("step_index"))
    created_at = _extract_turn_timestamp(record) or fallback_timestamp
    is_new = _is_turn_new(created_at, watermark_dt)

    agent_thoughts: list[str] = []
    planner_goals: list[str] = []
    tool_summaries: list[dict[str, str]] = []

    _process_planner_record(
        record=record,
        max_thought_chars=max_thought_chars,
        agent_thoughts=agent_thoughts,
        planner_goals=planner_goals,
        tool_summaries=tool_summaries,
    )

    thought_content = agent_thoughts[0] if agent_thoughts else ""
    if (
        not thought_content
        and record.get("content")
        and isinstance(record.get("content"), str)
    ):
        raw_c = record.get("content", "").strip()
        raw_c_clean = re.sub(r"<PLAN>.*?</PLAN>", "", raw_c, flags=re.DOTALL).strip()
        if raw_c_clean:
            if len(raw_c_clean) > max_thought_chars:
                raw_c_clean = raw_c_clean[:max_thought_chars] + "... [TRUNCATED]"
            thought_content = raw_c_clean

    if not thought_content and not planner_goals and not tool_summaries:
        return None

    return CompactTurn(
        step_index=step_index,
        created_at=created_at,
        turn_type="agent",
        content=thought_content,
        is_new=is_new,
        goals=planner_goals,
        tool_summaries=tool_summaries,
    )


def _is_turn_new(
    created_at: str | datetime | date | None, watermark_dt: datetime | None
) -> bool:
    """Determines whether a turn is new activity based on created_at and watermark."""
    if watermark_dt is None:
        return True
    if not created_at or not str(created_at).strip():
        return True
    try:
        turn_dt = _parse_iso_datetime(created_at)
        if turn_dt == datetime.min.replace(tzinfo=timezone.utc):
            return True
        return turn_dt > watermark_dt
    except (ValueError, TypeError):
        return True


def _parse_step_index(val: Any) -> int:
    """Safely coerces step index to integer with 0 fallback."""
    if val is None:
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def _extract_turn_timestamp(record: dict[str, Any]) -> str:
    """Extracts literal created_at ISO timestamp or fallback timestamp from a record."""
    for key in ("created_at", "timestamp", "time", "date"):
        val = record.get(key)
        if val is not None:
            clean_val = str(val).strip().strip("\"'")
            if clean_val:
                return clean_val

    meta_raw = record.get("metadata")
    if isinstance(meta_raw, str):
        try:
            meta_raw = json.loads(meta_raw)
        except (json.JSONDecodeError, TypeError):
            meta_raw = None

    if isinstance(meta_raw, dict):
        for key in ("created_at", "timestamp", "time", "date"):
            val = meta_raw.get(key)
            if val is not None:
                clean_val = str(val).strip().strip("\"'")
                if clean_val:
                    return clean_val

    content = str(record.get("content") or "")
    if "<ADDITIONAL_METADATA>" in content:
        meta_match = re.search(
            r"<ADDITIONAL_METADATA>(.*?)</ADDITIONAL_METADATA>",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        meta_text = meta_match.group(1) if meta_match else ""
        m_conv = re.search(
            r"(?:(?:current\s+)?(?:local\s+)?time\s+is):\s*([^\n\r<]+)",
            meta_text,
            re.IGNORECASE,
        )
        if m_conv:
            return m_conv.group(1).rstrip(".").strip().strip(".,;\"'[]")
        m_labeled = re.search(
            r"(?:^|\n)\s*(?:created_at|timestamp|time|date):\s*([^\n\r<]+)",
            meta_text,
            re.IGNORECASE,
        )
        if m_labeled:
            return m_labeled.group(1).rstrip(".").strip().strip(".,;\"'[]")
        m_iso = re.search(
            r"\b(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}(?::\d{2})?(?:[.\d]+)?(?:Z|[+-]\d{2}:?\d{2})?)\b",
            meta_text,
        )
        if m_iso:
            return m_iso.group(1).strip()
    return ""


def _process_planner_record(
    record: dict[str, Any],
    max_thought_chars: int,
    agent_thoughts: list[str],
    planner_goals: list[str],
    tool_summaries: list[dict[str, str]],
) -> None:
    """Processes a PLANNER_RESPONSE record, extracting thoughts, goals, and tool calls."""
    thinking = record.get("thinking")
    if thinking and isinstance(thinking, str):
        trimmed = thinking.strip()
        if len(trimmed) > max_thought_chars:
            trimmed = trimmed[:max_thought_chars] + "... [TRUNCATED]"
        if trimmed:
            agent_thoughts.append(trimmed)

    # Extract structured plan/goals if present
    plan_field = record.get("plan") or record.get("goals")
    if plan_field:
        if isinstance(plan_field, list):
            planner_goals.extend(str(item) for item in plan_field if item)
        elif isinstance(plan_field, str) and plan_field.strip():
            planner_goals.append(plan_field.strip())

    content = record.get("content")
    if content and isinstance(content, str):
        plan_block = re.search(r"<PLAN>(.*?)</PLAN>", content, re.DOTALL)
        if plan_block:
            planner_goals.append(plan_block.group(1).strip())

    tool_calls = record.get("tool_calls")
    if tool_calls and isinstance(tool_calls, list):
        for tc in tool_calls:
            if isinstance(tc, dict):
                summary = _extract_tool_summary(
                    tc, fallback_status=record.get("status") or "INVOKED"
                )
                tool_summaries.append(summary)


def _extract_tool_summary(tc: dict[str, Any], fallback_status: str) -> dict[str, str]:
    """Extracts compact metadata from a tool invocation dictionary."""
    name = str(tc.get("name") or tc.get("tool") or "")
    raw_args = tc.get("args") or tc.get("arguments") or {}
    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args)
        except (json.JSONDecodeError, TypeError):
            raw_args = {}
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}

    action = _clean_scalar_str(args.get("toolAction"))
    summary = _clean_scalar_str(args.get("toolSummary"))
    target = (
        _clean_scalar_str(args.get("TargetFile"))
        or _clean_scalar_str(args.get("AbsolutePath"))
        or _clean_scalar_str(args.get("CommandLine"))
        or _clean_scalar_str(args.get("SearchPath"))
        or _clean_scalar_str(args.get("DirectoryPath"))
        or _clean_scalar_str(args.get("NotebookPath"))
        or _clean_scalar_str(args.get("Url"))
        or _clean_scalar_str(args.get("Pattern"))
        or _clean_scalar_str(args.get("Query"))
        or _clean_scalar_str(args.get("query"))
        or ""
    )
    status = _clean_scalar_str(tc.get("status")) or fallback_status

    return {
        "tool": name,
        "toolAction": action,
        "toolSummary": summary,
        "action": action,
        "summary": summary,
        "target": target,
        "status": status,
    }


def _clean_scalar_str(val: Any) -> str:
    """Cleans string representations and strips redundant surrounding quotes."""
    if val is None:
        return ""
    text = str(val).strip()
    if len(text) >= 2 and (
        (text.startswith('"') and text.endswith('"'))
        or (text.startswith("'") and text.endswith("'"))
    ):
        return text[1:-1].strip()
    return text


# ============================================================================
# Category D: State Management
# ============================================================================


def load_state(state_file: str | Path = DEFAULT_STATE_FILE) -> DreamState:
    """Loads DreamState from disk or returns default initial state if missing.

    Recovers gracefully from corrupted JSON, empty files, or filesystem read errors.

    Args:
        state_file: Path to memory/.state.json.

    Returns:
        DreamState object populated from file or default values.
    """
    path = Path(state_file)
    if not path.is_file():
        return DreamState()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return DreamState()

        version = int(data.get("schema_version") or data.get("version") or 1)
        cold_start = bool(data.get("cold_start_completed", False))
        last_ts = str(
            data.get("last_consolidated_timestamp")
            or data.get("watermark_last_modified_time")
            or data.get("last_dream_timestamp")
            or ""
        )
        last_sid = str(data.get("last_consolidated_session_id") or "")
        processed = [
            str(sid) for sid in (data.get("processed_session_ids") or []) if sid
        ]
        cold_start_ts = data.get("cold_start_timestamp")
        last_dream_ts = data.get("last_dream_timestamp")
        watermark = data.get("watermark_last_modified_time") or (
            last_ts if last_ts else None
        )
        mode = str(data.get("last_run_mode", "turbo"))
        stats = dict(data.get("stats") or {})

        return DreamState(
            cold_start_completed=cold_start,
            last_consolidated_timestamp=last_ts,
            last_consolidated_session_id=last_sid,
            processed_session_ids=processed,
            schema_version=version,
            cold_start_timestamp=str(cold_start_ts) if cold_start_ts else None,
            last_dream_timestamp=str(last_dream_ts) if last_dream_ts else None,
            watermark_last_modified_time=str(watermark) if watermark else None,
            last_run_mode=mode,
            stats=stats,
        )
    except (json.JSONDecodeError, OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning(
            "Failed to load state file %s; defaulting to fresh state. Error: %s",
            path,
            exc,
        )
        return DreamState()


def save_state_atomic(
    state: DreamState,
    state_file: str | Path = DEFAULT_STATE_FILE,
) -> None:
    """Atomically persists DreamState to disk via .tmp write and os.replace.

    Guarantees atomic updates across process crashes and sudden termination.
    Keeps the temporary file in the same directory to prevent cross-device move
    failures on Windows.

    Args:
        state: DreamState object to serialize.
        state_file: Destination file path.
    """
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")

    payload = state.to_dict()
    payload["version"] = state.schema_version
    payload["watermark_last_modified_time"] = (
        state.watermark_last_modified_time or state.last_consolidated_timestamp or None
    )

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())

    os.replace(temp_path, path)


def update_state_watermark(
    state_file: str | Path,
    watermark: str,
    processed_ids: list[str],
) -> DreamState:
    """Advances watermark timestamp and appends processed session IDs.

    Args:
        state_file: Path to state file.
        watermark: New watermark ISO timestamp.
        processed_ids: List of session IDs consolidated in the batch.

    Returns:
        The updated and persisted DreamState object.
    """
    state = load_state(state_file)
    state.last_consolidated_timestamp = watermark
    state.watermark_last_modified_time = watermark
    existing = set(state.processed_session_ids)
    for sid in processed_ids:
        clean_sid = str(sid).strip()
        if clean_sid and clean_sid not in existing:
            state.processed_session_ids.append(clean_sid)
            existing.add(clean_sid)
    if processed_ids:
        state.last_consolidated_session_id = str(processed_ids[-1]).strip()
    save_state_atomic(state, state_file)
    return state


# Aliases for cross-module compatibility
load_dream_state = load_state
save_dream_state = save_state_atomic


# ============================================================================
# Category E: Manifest & Invariant Scanning
# ============================================================================


def scan_keyed_invariants(
    content: str,
    file_path: str = "",
) -> list[KeyedInvariant]:
    """Scans markdown content for Keyed Invariant specification blocks.

    Parses:
    - <!-- INVARIANT_KEY: <key> -->
    - <!-- LAST_CONFIRMED: <timestamp/session> -->
    - <!-- SUPERSEDES: <old_key> -->
    - **Target**: <target text>
    - **Invariant**: <invariant text>
    - **Negative Constraint**: <constraint text>
    - **Rationale**: <rationale text>

    Args:
        content: Markdown string to parse.
        file_path: Optional path of the source file for attribution.

    Returns:
        List of KeyedInvariant dataclasses extracted from the markdown.
    """
    if not content or not isinstance(content, str):
        return []

    key_pattern = re.compile(r"<!--\s*INVARIANT_KEY:\s*([^\s>]+)\s*-->")
    matches = list(key_pattern.finditer(content))
    if not matches:
        return []

    invariants: list[KeyedInvariant] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        chunk = content[start:end]
        key = match.group(1).strip()

        lc_match = re.search(r"<!--\s*LAST_CONFIRMED:\s*(.*?)\s*-->", chunk)
        sp_match = re.search(r"<!--\s*SUPERSEDES:\s*(.*?)\s*-->", chunk)

        target = _extract_invariant_field(chunk, "Target")
        invariant = _extract_invariant_field(chunk, "Invariant")
        neg_constraint = _extract_invariant_field(chunk, "Negative Constraint")
        rationale = _extract_invariant_field(chunk, "Rationale")

        invariants.append(
            KeyedInvariant(
                key=key,
                last_confirmed=lc_match.group(1).strip() if lc_match else "",
                supersedes=sp_match.group(1).strip() if sp_match else None,
                target=target,
                invariant=invariant,
                negative_constraint=neg_constraint,
                rationale=rationale,
                file_path=file_path,
            )
        )

    return invariants


def _extract_invariant_field(chunk: str, field_name: str) -> str:
    """Extracts the value of a specific named field inside an invariant markdown chunk."""
    pattern = (
        rf"(?:-\s*)?\*{{0,2}}{re.escape(field_name)}\*{{0,2}}:\s*(.*?)"
        rf"(?=(?:\n\s*(?:-\s*)?\*{{0,2}}(?:Target|Invariant|Negative Constraint|Rationale)\*{{0,2}}:|\Z))"
    )
    match = re.search(pattern, chunk, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def list_active_memory_files(
    memory_dir: str | Path,
    exclude_archive: bool = True,
    exclude_proposals: bool = False,
) -> list[Path]:
    """Lists all active markdown memory files in the memory directory.

    Recursively discovers markdown files while excluding dotfiles, temporary
    files, and optionally archive/ or proposals/ directories.

    Args:
        memory_dir: Path to the root memory directory.
        exclude_archive: Whether to exclude files under archive/.
        exclude_proposals: Whether to exclude files under proposals/.

    Returns:
        Sorted list of active markdown file Paths.
    """
    path = Path(memory_dir)
    if not path.is_dir():
        return []

    results: list[Path] = []
    for item in sorted(path.rglob("*.md")):
        if not item.is_file():
            continue
        parts = [p.lower() for p in item.parts]
        if any(p.startswith(".") for p in parts):
            continue
        if exclude_archive and "archive" in parts:
            continue
        if exclude_proposals and "proposals" in parts:
            continue
        results.append(item)
    return results


# Alias for compatibility with survey report
parse_keyed_invariants = scan_keyed_invariants


def register_domain_in_manifest(
    manifest_path: str | Path,
    slug: str,
    workspace_uri: str = "",
    aliases: list[str] | None = None,
    category: str = "projects",
) -> bool:
    """Dynamically registers a domain or project in dreaming/index.md.

    Inserts the new entry under the appropriate section if not already present.

    Args:
        manifest_path: Path to index.md manifest file.
        slug: Domain or project slug (e.g. 'bellhop' or 'home-assistant').
        workspace_uri: Optional file:/// URI for engineering projects.
        aliases: Optional list of alias strings.
        category: 'projects', 'domains', or 'people'.

    Returns:
        True if manifest was modified, False if already registered or error.
    """
    path = Path(manifest_path)
    if not path.is_file():
        return False

    content = path.read_text(encoding="utf-8")
    file_name = f"{slug}.md" if not slug.endswith(".md") else slug
    target_rel = f"memories/{file_name}"

    if target_rel in content:
        return False

    clean_aliases = aliases or [slug.replace("-", " ").title(), slug]
    aliases_str = ", ".join(clean_aliases)

    lines = content.splitlines()

    if category == "projects":
        section_header = "### Engineering Projects (`memories/`)"
        new_entry = [
            f"- `{target_rel}`:",
            f"  - Workspace: `{workspace_uri}`",
            f"  - Aliases: [{aliases_str}]",
        ]
    elif category == "people":
        section_header = "### People & Collaborators (`memories/`)"
        new_entry = [f"- `{target_rel}`: [{aliases_str}]"]
    else:
        section_header = "### Life Domains & Infrastructure (`memories/`)"
        new_entry = [f"- `{target_rel}`: [{aliases_str}]"]

    found_idx = -1
    for idx, line in enumerate(lines):
        if section_header in line:
            found_idx = idx
            break

    if found_idx != -1:
        lines.insert(found_idx + 1, "\n".join(new_entry))
    else:
        lines.extend(["", section_header] + new_entry)

    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return True


def prune_empty_domains_from_manifest(
    manifest_path: str | Path,
    memories_dir: str | Path,
) -> list[str]:
    """Prunes empty memory files and unreferenced stub domains from index.md.

    Scans memories/ directory and removes any domain or project markdown file
    that has 0 keyed invariants (excluding core preferences.md and guardrails.md).
    Then prunes manifest entries matching the removed files.

    Args:
        manifest_path: Path to dreaming/index.md.
        memories_dir: Path to dreaming/memories/ directory.

    Returns:
        List of pruned file names.
    """
    m_path = Path(manifest_path)
    mem_dir = Path(memories_dir)
    if not m_path.is_file() or not mem_dir.is_dir():
        return []

    removed_files: list[str] = []

    # 1. Inspect all files in memories_dir
    core_files = {"preferences.md", "guardrails.md"}
    active_files: set[str] = set()

    for item in mem_dir.glob("*.md"):
        if item.name in core_files:
            active_files.add(item.name)
            continue
        try:
            text = item.read_text(encoding="utf-8")
            invariants = scan_keyed_invariants(text)
            if len(invariants) == 0:
                item.unlink()
                removed_files.append(item.name)
            else:
                active_files.add(item.name)
        except Exception:
            active_files.add(item.name)

    # 2. Prune manifest entries for any file not in active_files
    content = m_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    new_lines: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        # Match project block: - `memories/<file>.md`:
        match_proj = re.match(r"^-\s*`memories/([^`]+)`\s*:\s*$", line)
        if match_proj:
            fname = match_proj.group(1).strip()
            sublines: list[str] = []
            j = i + 1
            while j < len(lines) and (lines[j].startswith("  ") or lines[j].startswith("\t")):
                sublines.append(lines[j])
                j += 1
            if fname not in active_files:
                if fname not in removed_files:
                    removed_files.append(fname)
            else:
                new_lines.append(line)
                new_lines.extend(sublines)
            i = j
            continue

        # Match single-line domain or person: - `memories/<file>.md`: [...]
        match_dom = re.match(r"^-\s*`memories/([^`]+)`\s*:\s*\[(.*?)\]", line)
        if match_dom:
            fname = match_dom.group(1).strip()
            if fname not in active_files:
                if fname not in removed_files:
                    removed_files.append(fname)
            else:
                new_lines.append(line)
            i += 1
            continue

        new_lines.append(line)
        i += 1

    m_path.write_text("\n".join(new_lines).strip() + "\n", encoding="utf-8")
    return removed_files
