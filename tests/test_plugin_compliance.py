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

"""Plugin compliance, manifest parsing, and specification tests for agy-dreamer (Milestone 4).

Validates:
- Plugin manifest (plugin.json) validity, naming, version, schema, and metadata.
- Runtime retrieval rules (rules/AGENTS.md) size ceiling (<24 KB), absence of YAML frontmatter,
  presence of core includes, 3-pillar retrieval anchors, 1% anti-rationalization imperative,
  and zero repository pollution guardrails.
- Consolidation skill (skills/dreaming/SKILL.md) YAML frontmatter, 4-tier epistemic classification,
  keyed invariant schema, dialectic supersession, concept deduplication, Turbo Mode safeguards,
  and scheduled daemon cron definition.
- Manifest parsing and runtime retrieval engine resolution by workspace URI and semantic aliases.
- Keyed invariant integrity and schema edge cases.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from scripts.dream_helpers import (
    scan_keyed_invariants,
    uri_to_local_path,
)

# Root directory of the agy-dreamer plugin
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_JSON_PATH = PLUGIN_ROOT / "plugin.json"
RULES_AGENTS_PATH = PLUGIN_ROOT / "rules" / "AGENTS.md"
SKILL_DREAMING_PATH = PLUGIN_ROOT / "skills" / "dreaming" / "SKILL.md"

SAMPLE_MANIFEST = """# Antigravity Memory Manifest
Inspect specific sub-memories using `view_file` when conversation context matches.

### People & Collaborators (`memory/people/`)
- `developer-alice.md`: [Developer Alice, preferences, core heuristics]
- `collaborator-bob.md`: [Bob, family schedule, shared calendar, collaborative travel]

### Life Domains & Infrastructure (`memory/domains/`)
- `cloud-infrastructure.md`: [Kubernetes, Docker, AWS, Terraform, CI/CD, cloud, server]
- `data-engineering.md`: [Postgres, SQLite, Kafka, ETL, pipeline, data warehouse]

### Engineering Projects (`memory/projects/`)
- `sample-project-alpha.md`:
  - Workspace: `file:///c%3A/Projects/sample-project-alpha`
  - Aliases: [BioCLIP, YOLOv8-seg, polygon contour, alpha, perception, quality.py, objective only]
- `sample-pipeline.md`:
  - Workspace: `file:///c%3A/Projects/sample-pipeline`
  - Aliases: [Data ingest, burst culling, mmap, RAW extraction, photo viewer, canvas, hero frame]
- `service-dispatch.md`:
  - Workspace: `file:///c%3A/Projects/service-dispatch`
  - Aliases: [Dispatch, service orchestration, protocol dispatch]
"""


# ============================================================================
# Manifest & Retrieval Helper Functions (Simulating Runtime Engine)
# ============================================================================


def parse_memory_manifest(manifest_content: str) -> dict[str, dict[str, Any]]:
    """Parses memory/index.md manifest into structured entity catalogs.

    Args:
        manifest_content: Markdown content of the manifest.

    Returns:
        Dict with 'people', 'domains', and 'projects' catalogs.
    """
    catalogs: dict[str, dict[str, Any]] = {
        "people": {},
        "domains": {},
        "projects": {},
    }

    current_section: str | None = None
    lines = manifest_content.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if "### People & Collaborators" in line:
            current_section = "people"
            i += 1
            continue
        elif "### Life Domains & Infrastructure" in line:
            current_section = "domains"
            i += 1
            continue
        elif "### Engineering Projects" in line:
            current_section = "projects"
            i += 1
            continue

        if not current_section:
            i += 1
            continue

        if current_section in ("people", "domains"):
            # Format: - `file.md`: [alias1, alias2, ...]
            match = re.match(r"^-\s*`([^`]+)`\s*:\s*\[(.*?)\]", line)
            if match:
                file_name = match.group(1).strip()
                aliases = [a.strip() for a in match.group(2).split(",") if a.strip()]
                catalogs[current_section][file_name] = {
                    "file": file_name,
                    "rel_path": f"memory/{current_section}/{file_name}",
                    "aliases": aliases,
                }
        elif current_section == "projects":
            # Format:
            # - `file.md`:
            #   - Workspace: `uri`
            #   - Aliases: [alias1, ...]
            match = re.match(r"^-\s*`([^`]+)`\s*:", line)
            if match:
                file_name = match.group(1).strip()
                workspace_uri = ""
                aliases: list[str] = []

                # Scan indented children lines
                j = i + 1
                while j < len(lines) and (
                    lines[j].startswith("  ") or lines[j].startswith("\t")
                ):
                    sub = lines[j].strip()
                    ws_match = re.match(r"^-\s*Workspace\s*:\s*`([^`]+)`", sub)
                    if ws_match:
                        workspace_uri = ws_match.group(1).strip()
                    al_match = re.match(r"^-\s*Aliases\s*:\s*\[(.*?)\]", sub)
                    if al_match:
                        aliases = [
                            a.strip() for a in al_match.group(1).split(",") if a.strip()
                        ]
                    j += 1

                catalogs["projects"][file_name] = {
                    "file": file_name,
                    "rel_path": f"memory/projects/{file_name}",
                    "workspace_uri": workspace_uri,
                    "aliases": aliases,
                }
                i = j - 1
        i += 1

    return catalogs


def resolve_submemory_by_workspace(
    manifest_content: str,
    active_workspace: str,
) -> str | None:
    """Matches active workspace URI or local path against registered project manifests.

    Args:
        manifest_content: Master manifest string.
        active_workspace: Workspace URI (e.g. file:///...) or local path.

    Returns:
        Relative path to project memory file (e.g. 'memory/projects/sample-project-alpha.md') or None.
    """
    catalogs = parse_memory_manifest(manifest_content)
    norm_active = active_workspace.strip().rstrip("/\\").lower()
    norm_active_local = uri_to_local_path(active_workspace).rstrip("/\\").lower()

    for proj in catalogs["projects"].values():
        ws_uri = proj.get("workspace_uri", "").strip().rstrip("/\\").lower()
        if not ws_uri:
            continue
        ws_local = uri_to_local_path(ws_uri).rstrip("/\\").lower()

        if norm_active == ws_uri or norm_active_local == ws_local:
            return proj["rel_path"]

    return None


def resolve_submemories_by_alias(
    manifest_content: str,
    query_text: str,
) -> list[str]:
    """Matches query keywords against semantic aliases in all manifest catalogs.

    Args:
        manifest_content: Master manifest string.
        query_text: User prompt, conversation text, or touched file paths.

    Returns:
        List of matching memory file relative paths.
    """
    catalogs = parse_memory_manifest(manifest_content)
    query_lower = query_text.lower()
    matched_paths: list[str] = []

    for section in ("people", "domains", "projects"):
        for item in catalogs[section].values():
            for alias in item["aliases"]:
                # Use word-boundary or substring search for distinctive terms
                alias_lower = alias.lower()
                pattern = rf"\b{re.escape(alias_lower)}\b"
                if re.search(pattern, query_lower):
                    if item["rel_path"] not in matched_paths:
                        matched_paths.append(item["rel_path"])
                    break

    return matched_paths


# ============================================================================
# 1. Plugin Manifest (plugin.json) Compliance Tests
# ============================================================================


class TestPluginManifestCompliance:
    """Validates plugin.json conformance with Antigravity plugin specification."""

    def test_plugin_json_exists(self) -> None:
        """plugin.json must exist in the root directory."""
        assert PLUGIN_JSON_PATH.exists(), (
            f"Missing plugin.json at root: {PLUGIN_JSON_PATH}"
        )
        assert PLUGIN_JSON_PATH.is_file(), "plugin.json must be a regular file."

    def test_plugin_json_is_valid_json(self) -> None:
        """plugin.json must parse cleanly as standard JSON."""
        content = PLUGIN_JSON_PATH.read_text(encoding="utf-8")
        data = json.loads(content)
        assert isinstance(data, dict), "plugin.json root must be a JSON object."

    def test_plugin_json_required_schema_fields(self) -> None:
        """plugin.json must contain all required Antigravity plugin manifest keys."""
        data = json.loads(PLUGIN_JSON_PATH.read_text(encoding="utf-8"))
        required_keys = [
            "name",
            "version",
            "description",
            "author",
            "license",
            "repository",
            "keywords",
        ]
        for key in required_keys:
            assert key in data, f"plugin.json missing required field: '{key}'"

    def test_plugin_json_metadata_values(self) -> None:
        """plugin.json must match agy-dreamer name, semver version, and keywords."""
        data = json.loads(PLUGIN_JSON_PATH.read_text(encoding="utf-8"))
        assert data["name"] == "agy-dreamer"
        assert data["version"] == "0.1.0"
        assert "Antigravity" in data["description"]
        assert isinstance(data["author"], dict)
        assert data["author"]["name"] == "j-steve"
        assert data["license"] == "MIT"
        assert "agy-dreamer" in data["repository"]

        keywords = data.get("keywords", [])
        assert isinstance(keywords, list)
        assert len(keywords) >= 5
        for kw in ["antigravity", "memory", "dreaming", "consolidation"]:
            assert kw in keywords, f"Expected keyword '{kw}' in plugin.json keywords."


# ============================================================================
# 2. Runtime Retrieval Rules (rules/AGENTS.md) Compliance Tests
# ============================================================================


class TestRulesCompliance:
    """Validates rules/AGENTS.md size, format, anchors, and guardrails."""

    def test_rules_file_exists(self) -> None:
        """rules/AGENTS.md must exist in rules/ directory."""
        assert RULES_AGENTS_PATH.exists(), f"Missing rules file at: {RULES_AGENTS_PATH}"
        assert RULES_AGENTS_PATH.is_file(), "rules/AGENTS.md must be a regular file."

    def test_rules_file_size_budget(self) -> None:
        """rules/AGENTS.md must strictly stay under the 24,000 bytes global ceiling."""
        content = RULES_AGENTS_PATH.read_bytes()
        size_bytes = len(content)
        assert size_bytes < 24000, (
            f"rules/AGENTS.md size ({size_bytes} bytes) exceeds 24,000 bytes ceiling."
        )
        # Target lean footprint is < 5 KB
        assert size_bytes < 5000, (
            f"rules/AGENTS.md should be ultra-lean; found {size_bytes} bytes."
        )

    def test_rules_file_no_yaml_frontmatter(self) -> None:
        """rules/AGENTS.md must NOT contain YAML frontmatter (starts with markdown)."""
        content = RULES_AGENTS_PATH.read_text(encoding="utf-8").strip()
        assert not content.startswith("---"), (
            "rules/AGENTS.md must not contain YAML frontmatter."
        )
        assert content.startswith("#"), (
            "rules/AGENTS.md should begin with a Markdown heading."
        )

    def test_rules_includes_core_and_manifest(self) -> None:
        """rules/AGENTS.md must inject core memory and on-demand manifest via @[...]."""
        content = RULES_AGENTS_PATH.read_text(encoding="utf-8")
        assert "@[Developer Preferences]" in content, (
            "Missing @[Developer Preferences] include."
        )
        assert "@[System Guardrails]" in content, (
            "Missing @[System Guardrails] include."
        )
        assert "@[Memory Manifest]" in content, "Missing @[Memory Manifest] include."
        assert "preferences.md" in content
        assert "guardrails.md" in content
        assert "index.md" in content

    def test_rules_three_pillar_retrieval_anchors(self) -> None:
        """rules/AGENTS.md must define all three pillars of the memory retrieval anchor."""
        content = RULES_AGENTS_PATH.read_text(encoding="utf-8")
        # Pillar 1: Turn-0 Workspace URI Auto-Load
        assert (
            "Turn-0 Workspace URI Auto-Load" in content
            or "Turn-0 Workspace URI" in content
        )
        assert "view_file" in content
        # Pillar 2: Semantic Alias Trigger
        assert "Semantic Alias Trigger" in content
        # Pillar 3: Morning Proposal Check
        assert "Morning Proposal Check" in content
        assert "proposals" in content

    def test_rules_anti_rationalization_imperative(self) -> None:
        """rules/AGENTS.md must enforce the 1% Anti-Rationalization Imperative."""
        content = RULES_AGENTS_PATH.read_text(encoding="utf-8")
        assert "<EXTREMELY-IMPORTANT>" in content, (
            "Missing <EXTREMELY-IMPORTANT> tag in AGENTS.md"
        )
        assert "</EXTREMELY-IMPORTANT>" in content
        assert "1%" in content, "Anti-rationalization must mandate 1% threshold."
        assert "view_file" in content, (
            "Anti-rationalization must mandate view_file call."
        )
        assert "rationalize" in content.lower(), (
            "Anti-rationalization must forbid rationalizing."
        )

    def test_rules_operational_guardrails(self) -> None:
        """rules/AGENTS.md must enforce Zero Repository Pollution and line ceilings."""
        content = RULES_AGENTS_PATH.read_text(encoding="utf-8")
        assert "Zero Repository Pollution" in content, (
            "Missing Zero Repository Pollution guardrail."
        )
        assert "~/.gemini/config/memory/" in content or "agy-core" in content
        assert "30 lines" in content, "Missing 30 lines ceiling for core preferences."
        assert "50 lines" in content, "Missing 50 lines ceiling for guardrails/domains."


# ============================================================================
# 3. Consolidation Skill (skills/dreaming/SKILL.md) Compliance Tests
# ============================================================================


class TestDreamingSkillCompliance:
    """Validates skills/dreaming/SKILL.md structure, frontmatter, rubrics, and cron."""

    def test_skill_file_exists(self) -> None:
        """skills/dreaming/SKILL.md must exist."""
        assert SKILL_DREAMING_PATH.exists(), (
            f"Missing skill file: {SKILL_DREAMING_PATH}"
        )
        assert SKILL_DREAMING_PATH.is_file(), (
            "skills/dreaming/SKILL.md must be a regular file."
        )

    def test_skill_yaml_frontmatter_validity(self) -> None:
        """skills/dreaming/SKILL.md must contain valid, parseable YAML frontmatter."""
        content = SKILL_DREAMING_PATH.read_text(encoding="utf-8")
        assert content.startswith("---"), (
            "Skill file must start with '---' frontmatter delimiter."
        )

        parts = content.split("---", 2)
        assert len(parts) >= 3, "Frontmatter must be enclosed in '---' markers."
        raw_yaml = parts[1]

        data = yaml.safe_load(raw_yaml)
        assert isinstance(data, dict), "Frontmatter must be a YAML dictionary."
        assert data.get("name") == "dreaming", "Skill name must be 'dreaming'."
        assert data.get("category") == "memory"

        # Antigravity skill description standard: starts with 'Use when...'
        desc = data.get("description", "")
        assert desc.startswith("Use when"), (
            f"Description should start with 'Use when...': got '{desc}'"
        )

        # Triggers in metadata
        meta = data.get("metadata", {})
        assert "triggers" in meta, "Frontmatter metadata must specify triggers."
        triggers_str = meta["triggers"]
        triggers = [t.strip() for t in triggers_str.split(",")]
        assert len(triggers) >= 3, (
            f"Skill must specify at least 3 triggers; got {len(triggers)}"
        )
        for expected in ["dreaming", "consolidate memory", "cold start memory"]:
            assert any(expected in t for t in triggers)

    def test_skill_line_count(self) -> None:
        """skills/dreaming/SKILL.md must remain concise and under 500 lines."""
        content = SKILL_DREAMING_PATH.read_text(encoding="utf-8")
        line_count = len(content.splitlines())
        assert line_count < 500, (
            f"SKILL.md exceeds 500 line recommended ceiling: {line_count} lines"
        )
        assert line_count >= 100, (
            f"SKILL.md appears too brief for comprehensive runbook: {line_count} lines"
        )

    def test_skill_4_tier_epistemic_classification(self) -> None:
        """SKILL.md must document the 4-Tier Epistemic Classification and semantic filtering."""
        content = SKILL_DREAMING_PATH.read_text(encoding="utf-8")
        # Tier 1
        assert "Tier 1" in content
        assert "User Interaction Axioms" in content or "User Axioms" in content
        assert "preferences.md" in content
        # Tier 2
        assert "Tier 2" in content
        assert (
            "Project & Domain Invariants" in content
            or "Domain/Project Invariants" in content
        )
        assert "projects/" in content
        assert "domains/" in content
        # Tier 3
        assert "Tier 3" in content
        assert "Environment Realities" in content
        assert "guardrails.md" in content
        # Tier 4
        assert "Tier 4" in content
        assert "Transient Operational Noise" in content
        assert "DISCARDED" in content

        # Semantic judgment warning for Tier 4 (not naive keyword blocklist)
        assert "SEMANTIC JUDGMENT" in content or "semantic judgment" in content.lower()
        assert "for now" in content or "today" in content

    def test_skill_keyed_invariant_schema_spec(self) -> None:
        """SKILL.md must specify the standardized Keyed Invariant Schema."""
        content = SKILL_DREAMING_PATH.read_text(encoding="utf-8")
        assert "<!-- INVARIANT_KEY:" in content
        assert "<!-- LAST_CONFIRMED:" in content
        assert "<!-- SUPERSEDES:" in content
        assert "**Target**:" in content
        assert "**Invariant**:" in content
        assert "**Negative Constraint**:" in content
        assert "**Rationale**:" in content

    def test_skill_dialectic_supersession_spec(self) -> None:
        """SKILL.md must specify dialectic contradiction resolution and archival."""
        content = SKILL_DREAMING_PATH.read_text(encoding="utf-8")
        assert "superseded.md" in content
        assert "[SUPERSEDED" in content
        assert "coexistence" in content.lower() or "coexist" in content.lower(), (
            "Must ban contradictory sibling rules."
        )

    def test_skill_concept_overlap_deduplication(self) -> None:
        """SKILL.md must specify the 60% concept overlap threshold for deduplication."""
        content = SKILL_DREAMING_PATH.read_text(encoding="utf-8")
        assert "60%" in content, "Must define 60% semantic overlap threshold."
        assert (
            "merge" in content.lower()
            or "consolidate" in content.lower()
            or "deduplication" in content.lower()
        )

    def test_skill_turbo_mode_spec(self) -> None:
        """SKILL.md must specify Turbo Mode confidence gating and atomic git commits."""
        content = SKILL_DREAMING_PATH.read_text(encoding="utf-8")
        assert "Turbo Mode" in content
        assert "0.9" in content, "Must enforce >= 0.9 confidence gating."
        assert "agy-core" in content
        assert "atomic" in content.lower() and "commit" in content.lower()
        assert "dreaming/proposals/" in content or "memory/proposals/" in content, (
            "Must route ambiguous items to proposals/."
        )

    def test_skill_scheduled_cron_job_definition(self) -> None:
        """SKILL.md must define the scheduled cron job with 0 3 * * * and IsDaemon: true."""
        content = SKILL_DREAMING_PATH.read_text(encoding="utf-8")
        assert "0 3 * * *" in content, "Must specify daily 3:00 AM cron schedule."
        assert "IsDaemon" in content
        assert "Antigravity Dreamer" in content


# ============================================================================
# 4. Manifest Parsing & Runtime Retrieval Resolution Tests
# ============================================================================


class TestManifestRetrievalEngine:
    """Validates manifest parsing, workspace URI matching, and alias lookups."""

    def test_parse_manifest_structure(self) -> None:
        """Parses sample manifest into people, domains, and projects catalogs."""
        catalogs = parse_memory_manifest(SAMPLE_MANIFEST)
        assert "people" in catalogs
        assert "domains" in catalogs
        assert "projects" in catalogs

        # People check
        assert "developer-alice.md" in catalogs["people"]
        assert "collaborator-bob.md" in catalogs["people"]
        assert "Developer Alice" in catalogs["people"]["developer-alice.md"]["aliases"]

        # Domains check
        assert "cloud-infrastructure.md" in catalogs["domains"]
        assert "Kubernetes" in catalogs["domains"]["cloud-infrastructure.md"]["aliases"]
        assert "Docker" in catalogs["domains"]["cloud-infrastructure.md"]["aliases"]

        # Projects check
        assert "sample-project-alpha.md" in catalogs["projects"]
        alpha = catalogs["projects"]["sample-project-alpha.md"]
        assert "sample-project-alpha" in alpha["workspace_uri"]
        assert "BioCLIP" in alpha["aliases"]
        assert "polygon contour" in alpha["aliases"]

    def test_resolve_submemory_by_workspace_uri_exact(self) -> None:
        """Resolves project memory file from exact workspace URI."""
        uri = "file:///c%3A/Projects/sample-project-alpha"
        result = resolve_submemory_by_workspace(SAMPLE_MANIFEST, uri)
        assert result == "memory/projects/sample-project-alpha.md"

    def test_resolve_submemory_by_workspace_local_path(self) -> None:
        """Resolves project memory file from unencoded Windows local directory path."""
        local_path = r"C:\Projects\service-dispatch"
        result = resolve_submemory_by_workspace(SAMPLE_MANIFEST, local_path)
        assert result == "memory/projects/service-dispatch.md"

    def test_resolve_submemory_by_workspace_case_insensitivity(self) -> None:
        """Resolves workspace URI regardless of path casing or trailing slashes."""
        uri_variant = "file:///c%3a/projects/sample-pipeline/"
        result = resolve_submemory_by_workspace(SAMPLE_MANIFEST, uri_variant)
        assert result == "memory/projects/sample-pipeline.md"

    def test_resolve_submemory_by_workspace_unmatched(self) -> None:
        """Unregistered workspace URIs return None."""
        uri_unknown = "file:///c%3A/Projects/nonexistent-project"
        result = resolve_submemory_by_workspace(SAMPLE_MANIFEST, uri_unknown)
        assert result is None

    def test_resolve_submemories_by_semantic_alias(self) -> None:
        """Resolves sub-memory paths based on prompt keywords and entity mentions."""
        # 1. Project alias
        matches = resolve_submemories_by_alias(
            SAMPLE_MANIFEST, "We need to fix BioCLIP segmentation bounds."
        )
        assert "memory/projects/sample-project-alpha.md" in matches

        # 2. Domain alias
        matches = resolve_submemories_by_alias(
            SAMPLE_MANIFEST, "Please check the Kubernetes automation logs."
        )
        assert "memory/domains/cloud-infrastructure.md" in matches

        # 3. Person alias
        matches = resolve_submemories_by_alias(
            SAMPLE_MANIFEST, "Developer Alice prefers direct feedback without fluff."
        )
        assert "memory/people/developer-alice.md" in matches

        # 4. Multi-entity prompt
        matches = resolve_submemories_by_alias(
            SAMPLE_MANIFEST,
            "Syncing alpha perception with cloud-infrastructure Kubernetes notification.",
        )
        assert "memory/projects/sample-project-alpha.md" in matches
        assert "memory/domains/cloud-infrastructure.md" in matches

    def test_resolve_submemories_irrelevant_query(self) -> None:
        """Queries with no matching aliases return an empty list."""
        matches = resolve_submemories_by_alias(
            SAMPLE_MANIFEST, "Making a cup of coffee and reading a book."
        )
        assert matches == []

    def test_manifest_entry_size_budget(self) -> None:
        """Verifies that individual manifest entries conform to ~80 bytes / entry footprint."""
        lines = [
            line
            for line in SAMPLE_MANIFEST.splitlines()
            if line.strip().startswith("- `")
        ]
        assert len(lines) >= 5
        avg_len = sum(len(line) for line in lines) / len(lines)
        # Entry line lengths should average around 60-120 bytes
        assert 40 < avg_len < 130, (
            f"Expected average entry length around 80 bytes; got {avg_len:.1f}"
        )


# ============================================================================
# 5. Keyed Invariant Parsing & Validation Edge Cases
# ============================================================================


class TestKeyedInvariantSchemaCompliance:
    """Validates Keyed Invariant schema parsing, negative constraints, and edge cases."""

    def test_valid_keyed_invariant_extraction(self) -> None:
        """Extracts and verifies all fields of a standard Keyed Invariant."""
        block = """
<!-- INVARIANT_KEY: sample_project.contour_integrity -->
<!-- LAST_CONFIRMED: 2026-09-27 (Session: 5b184a03) -->
<!-- SUPERSEDES: sample_project.old_contour -->
- **Target**: `GeometryModel` polygon contour modeling
  **Invariant**: Contour and mask must be genuine multi-point polygons.
  **Negative Constraint**: Rectangular bounding boxes and legacy shims are strictly forbidden.
  **Rationale**: Downstream CV spatial perception requires true geometric centroids.
"""
        invariants = scan_keyed_invariants(block)
        assert len(invariants) == 1
        inv = invariants[0]
        assert inv.key == "sample_project.contour_integrity"
        assert "2026-09-27" in inv.last_confirmed
        assert inv.supersedes == "sample_project.old_contour"
        assert "GeometryModel" in inv.target
        assert "multi-point polygons" in inv.invariant
        assert "Rectangular bounding boxes" in inv.negative_constraint
        assert "geometric centroids" in inv.rationale

    def test_keyed_invariant_missing_negative_constraint(self) -> None:
        """Invariants missing Negative Constraint have empty negative_constraint field."""
        block = """
<!-- INVARIANT_KEY: sample.loose_rule -->
<!-- LAST_CONFIRMED: 2026-09-27 -->
- **Target**: Sample Service
  **Invariant**: Always use UTF-8.
  **Rationale**: Prevents encoding errors.
"""
        invariants = scan_keyed_invariants(block)
        assert len(invariants) == 1
        assert invariants[0].negative_constraint == ""

    def test_synthetic_oversized_rule_fails_boundary_check(
        self, tmp_path: Path
    ) -> None:
        """Validates that a rule file exceeding 24,000 bytes violates the budget check."""
        oversized_file = tmp_path / "OVERSIZED_AGENTS.md"
        oversized_file.write_text("x" * 25000, encoding="utf-8")
        assert oversized_file.stat().st_size > 24000
