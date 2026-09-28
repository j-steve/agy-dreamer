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

"""Unit tests for the automated setup script (scripts/setup_dreamer.py)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.setup_dreamer import resolve_or_create_project, setup_dreamer


def test_resolve_or_create_project_creates_new(tmp_path: Path) -> None:
    """Verifies that a new project file is created when none exists."""
    config_dir = tmp_path / "config"
    dreaming_dir = config_dir / "dreaming"

    project_id = resolve_or_create_project(config_dir, dreaming_dir)
    assert project_id is not None
    assert len(project_id) > 10

    project_file = config_dir / "projects" / f"{project_id}.json"
    assert project_file.exists()

    data = json.loads(project_file.read_text(encoding="utf-8"))
    assert data["id"] == project_id
    assert data["name"] == "dreaming"


def test_resolve_or_create_project_reuses_existing(tmp_path: Path) -> None:
    """Verifies that an existing project with name 'dreaming' is reused."""
    config_dir = tmp_path / "config"
    dreaming_dir = config_dir / "dreaming"
    projects_dir = config_dir / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    existing_id = "test-dreaming-uuid-123"
    existing_data = {
        "id": existing_id,
        "name": "dreaming",
        "projectResources": {"resources": []},
    }
    (projects_dir / f"{existing_id}.json").write_text(
        json.dumps(existing_data), encoding="utf-8"
    )

    project_id = resolve_or_create_project(config_dir, dreaming_dir)
    assert project_id == existing_id


def test_setup_dreamer_full_pipeline(tmp_path: Path) -> None:
    """Verifies the complete setup pipeline across all files and directories."""
    config_dir = tmp_path / "config"
    config_json_path = config_dir / "config.json"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_json_path.write_text(json.dumps({"userSettings": {}}), encoding="utf-8")

    setup_dreamer(config_dir=config_dir, cron="0 4 * * *", bootstrap=False)

    # 1. Directories exist
    dreaming_dir = config_dir / "dreaming"
    assert (dreaming_dir / "memories").is_dir()
    assert (dreaming_dir / "proposals").is_dir()
    assert (dreaming_dir / "archive").is_dir()
    assert (dreaming_dir / ".state.json").is_file()

    # 2. Sidecar created
    sidecar_file = config_dir / "sidecars" / "nightly-dreaming" / "sidecar.json"
    assert sidecar_file.is_file()
    sidecar_data = json.loads(sidecar_file.read_text(encoding="utf-8"))
    assert sidecar_data["builtin"] == "schedule"
    assert sidecar_data["args"][0] == "0 4 * * *"
    assert "Execute the dreaming skill" in sidecar_data["args"][4]

    # 3. Config.json updated
    config_data = json.loads(config_json_path.read_text(encoding="utf-8"))
    assert config_data["plugins"]["agy-dreamer"]["enabled"] is True
    assert config_data["sidecars"]["nightly-dreaming"]["enabled"] is True
    assert config_data["sidecars"]["nightly-dreaming"]["projectId"] is not None
