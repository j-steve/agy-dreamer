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

"""Plugin compliance, manifest parsing, and Dreaming v2 specification tests for agy-dreamer."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from scripts.dream_helpers import (
    scan_memory_bullets,
    uri_to_local_path,
)

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_JSON_PATH = PLUGIN_ROOT / "plugin.json"
RULES_AGENTS_PATH = PLUGIN_ROOT / "rules" / "AGENTS.md"
SKILL_DREAMING_PATH = PLUGIN_ROOT / "skills" / "dreaming" / "SKILL.md"

SAMPLE_MANIFEST = """# Antigravity Dreaming Manifest
Inspect specific sub-memories in `memories/` using `view_file` when conversation context matches.

### People & Collaborators (`memories/`)
- `memories/developer-alice.md`: [Developer Alice, preferences, core heuristics]
- `memories/collaborator-bob.md`: [Bob, family schedule, shared calendar, collaborative travel]

### Life Domains & Infrastructure (`memories/`)
- `memories/cloud-infrastructure.md`: [Kubernetes, Docker, AWS, Terraform, CI/CD, cloud, server]
- `memories/data-engineering.md`: [Postgres, SQLite, Kafka, ETL, pipeline, data warehouse]

### Engineering Projects (`memories/`)
- `memories/sample-project-alpha.md`:
  - Workspace: `file:///c%3A/Projects/sample-project-alpha`
  - Aliases: [BioCLIP, YOLOv8-seg, polygon contour, alpha, perception, quality.py, objective only]
- `memories/sample-pipeline.md`:
  - Workspace: `file:///c%3A/Projects/sample-pipeline`
  - Aliases: [Data ingest, burst culling, mmap, RAW extraction, photo viewer, canvas, hero frame]
- `memories/service-dispatch.md`:
  - Workspace: `file:///c%3A/Projects/service-dispatch`
  - Aliases: [Dispatch, service orchestration, protocol dispatch]
"""


def parse_memory_manifest(manifest_content: str) -> dict[str, dict[str, Any]]:
    """Parses dreaming/index.md manifest into structured entity catalogs."""
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
        if "### Life Domains & Infrastructure" in line:
            current_section = "domains"
            i += 1
            continue
        if "### Engineering Projects" in line:
            current_section = "projects"
            i += 1
            continue

        if not current_section:
            i += 1
            continue

        if current_section in ("people", "domains"):
            match = re.match(r"^-\s*`([^`]+)`\s*:\s*\[(.*?)\]", line)
            if match:
                rel_path = match.group(1).strip()
                file_name = Path(rel_path).name
                aliases = [a.strip() for a in match.group(2).split(",") if a.strip()]
                catalogs[current_section][file_name] = {
                    "file": file_name,
                    "rel_path": rel_path,
                    "aliases": aliases,
                }
        elif current_section == "projects":
            match = re.match(r"^-\s*`([^`]+)`\s*:", line)
            if match:
                rel_path = match.group(1).strip()
                file_name = Path(rel_path).name
                workspace_uri = ""
                aliases = []

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
                    "rel_path": rel_path,
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
    """Matches active workspace URI or local path against registered project manifests."""
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
    """Matches query keywords against semantic aliases in all manifest catalogs."""
    catalogs = parse_memory_manifest(manifest_content)
    query_lower = query_text.lower()
    matched_paths: list[str] = []

    for section in ("people", "domains", "projects"):
        for item in catalogs[section].values():
            for alias in item["aliases"]:
                pattern = rf"\b{re.escape(alias.lower())}\b"
                if re.search(pattern, query_lower):
                    if item["rel_path"] not in matched_paths:
                        matched_paths.append(item["rel_path"])
                    break

    return matched_paths


class TestPluginManifestCompliance:
    """Validates plugin.json conformance with Antigravity plugin specification."""

    def test_plugin_json_exists_and_parses(self) -> None:
        assert PLUGIN_JSON_PATH.is_file()
        data = json.loads(PLUGIN_JSON_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert data["name"] == "agy-dreamer"
        assert data["version"] == "2.0.0"
        assert data["author"]["name"] == "j-steve"
        assert data["license"] == "MIT"
        for kw in ["antigravity", "memory", "dreaming", "consolidation"]:
            assert kw in data["keywords"]


class TestRulesCompliance:
    """Validates rules/AGENTS.md size, format, retrieval triggers, and guardrails."""

    def test_rules_file_size_and_format(self) -> None:
        assert RULES_AGENTS_PATH.is_file()
        raw_bytes = RULES_AGENTS_PATH.read_bytes()
        assert len(raw_bytes) < 3000
        content = raw_bytes.decode("utf-8").strip()
        assert not content.startswith("---")
        assert content.startswith("#")

    def test_rules_manifest_and_triggers(self) -> None:
        content = RULES_AGENTS_PATH.read_text(encoding="utf-8")
        assert "@[Memory Manifest]" in content
        assert "index.md" in content
        assert "Turn-0 Workspace URI Auto-Load" in content
        assert "Semantic Entity & Domain Trigger" in content
        assert "view_file" in content

    def test_rules_operational_guardrails(self) -> None:
        content = RULES_AGENTS_PATH.read_text(encoding="utf-8")
        assert "Zero Repository Pollution" in content
        assert "Secret Hygiene" in content
        assert "sync_credentials.py" in content
        assert "500 lines" in content


class TestDreamingSkillCompliance:
    """Validates skills/dreaming/SKILL.md v2 architecture, Repo-Blindness Gate, and sync."""

    def test_skill_yaml_frontmatter_validity(self) -> None:
        content = SKILL_DREAMING_PATH.read_text(encoding="utf-8")
        assert content.startswith("---")
        parts = content.split("---", 2)
        data = yaml.safe_load(parts[1])
        assert data["name"] == "dreaming"
        assert data["category"] == "memory"
        assert data["description"].startswith("Use when")
        triggers = [t.strip() for t in data["metadata"]["triggers"].split(",")]
        assert len(triggers) >= 4

    def test_skill_line_count_and_calm_prose(self) -> None:
        content = SKILL_DREAMING_PATH.read_text(encoding="utf-8")
        line_count = len(content.splitlines())
        assert 100 <= line_count < 350
        for forbidden_shout in ["NEVER", "ALWAYS", "STRICT COGNITIVE PROHIBITION"]:
            assert forbidden_shout not in content

    def test_skill_v2_core_mechanisms(self) -> None:
        content = SKILL_DREAMING_PATH.read_text(encoding="utf-8")
        assert "Repo-Blindness Gate" in content
        assert "Secret Hygiene" in content
        assert "sync_credentials.py" in content
        assert "Atomic Bullets" in content
        assert "<!-- INVARIANT_KEY -->" in content  # explicitly banned in formatting guidelines
        assert "git log -p dreaming/" in content
        assert "dreaming/.state.json" in content
        assert "pull --rebase --autostash" in content
        assert "AGENTS.md" in content
        assert "dreaming/proposals/" in content
        assert "Weekly Deep Dream" in content
        assert "0 3,13 * * *" in content


class TestManifestRetrievalEngine:
    """Validates manifest parsing, workspace URI matching, and alias lookups."""

    def test_parse_manifest_and_workspace_resolution(self) -> None:
        catalogs = parse_memory_manifest(SAMPLE_MANIFEST)
        assert "developer-alice.md" in catalogs["people"]
        assert "cloud-infrastructure.md" in catalogs["domains"]
        assert "sample-project-alpha.md" in catalogs["projects"]

        assert (
            resolve_submemory_by_workspace(
                SAMPLE_MANIFEST, "file:///c%3A/Projects/sample-project-alpha"
            )
            == "memories/sample-project-alpha.md"
        )
        assert (
            resolve_submemory_by_workspace(
                SAMPLE_MANIFEST, r"C:\Projects\service-dispatch"
            )
            == "memories/service-dispatch.md"
        )
        assert (
            resolve_submemory_by_workspace(
                SAMPLE_MANIFEST, "file:///c%3A/Projects/unknown"
            )
            is None
        )

    def test_resolve_submemories_by_semantic_alias(self) -> None:
        matches = resolve_submemories_by_alias(
            SAMPLE_MANIFEST,
            "Syncing alpha perception with cloud-infrastructure Kubernetes notification.",
        )
        assert "memories/sample-project-alpha.md" in matches
        assert "memories/cloud-infrastructure.md" in matches
        assert (
            resolve_submemories_by_alias(SAMPLE_MANIFEST, "Making a cup of coffee.")
            == []
        )


class TestMemoryBulletParsing:
    """Validates Dreaming v2 topical bullet parsing and metadata exclusion."""

    def test_topical_bullet_and_date_extraction(self) -> None:
        md = """# Home Automation
- **Runbook Skill**: `skills/home-assistant/SKILL.md`

## Lighting & Sensors
- **Wake-Up Curve**: Exponential 30-minute ramp reaching 100% at T-5m. (2026-11-10)
- **Kitchen Motion**: Node 42 HSM200 retains temperature calibration offset.
"""
        bullets = scan_memory_bullets(md)
        assert len(bullets) == 2
        assert bullets[0].section == "Lighting & Sensors"
        assert bullets[0].topic == "Wake-Up Curve"
        assert bullets[0].confirmed_date == "2026-11-10"
        assert "Exponential 30-minute ramp" in bullets[0].body
        assert bullets[1].topic == "Kitchen Motion"
        assert bullets[1].confirmed_date == ""
