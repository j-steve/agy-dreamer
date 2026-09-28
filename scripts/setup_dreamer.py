#!/usr/bin/env python3
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

"""One-Click Automated Setup for the agy-dreamer Antigravity Plugin.

Fully configures dreaming in your global Antigravity environment:
1. Enables the 'agy-dreamer' plugin in ~/.gemini/config/config.json.
2. Scaffolds ~/.gemini/config/dreaming/{memories,proposals,archive}.
3. Registers the dedicated 'dreaming' project workspace in Antigravity.
4. Creates and schedules the 'nightly-dreaming' sidecar daemon.
5. Optionally bootstraps cold-start historical memories immediately.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote

DEFAULT_CRON = "0 3 * * *"

DEFAULT_PROMPT = """Execute the dreaming skill to consolidate memories into agy-core:
1. Check if cold-start is needed in dreaming/.state.json; if so, bootstrap baseline memories.
2. Otherwise, scan root sessions modified since the watermark timestamp.
3. Extract invariants using the 4-tier epistemic rubric and auto-commit in Turbo Mode (>= 0.9 confidence).
4. Display a clean morning summary card in chat of all changes made. If no new sessions exist, report "No new sessions to consolidate" and finish."""


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, io.UnsupportedOperation, OSError):
        pass


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        print(f"  [!] Warning: Failed to load {path}: {e}", file=sys.stderr)
        return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=2, ensure_ascii=False)
        fp.write("\n")
    tmp_path.replace(path)


def resolve_or_create_project(config_dir: Path, dreaming_dir: Path) -> str:
    """Finds existing 'dreaming' project UUID or registers a new project in ~/.gemini/config/projects/."""
    projects_dir = config_dir / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    norm_dreaming = dreaming_dir.resolve()

    # Check for existing project matching path or name
    for pfile in projects_dir.glob("*.json"):
        pdata = _load_json(pfile)
        # Check name
        if pdata.get("name", "").lower() == "dreaming":
            pid = pdata.get("id") or pfile.stem
            print(f"  [+] Found existing Antigravity project 'dreaming' (ID: {pid})")
            return pid

        # Check folder URI
        resources = pdata.get("projectResources", {}).get("resources", [])
        for res in resources:
            uri = res.get("gitFolder", {}).get("folderUri", "")
            if uri.startswith("file:///"):
                clean = uri[8:]
                clean = re.sub(r"^([a-zA-Z])%3A", r"\1:", clean)
                try:
                    if Path(unquote(clean)).resolve() == norm_dreaming:
                        pid = pdata.get("id") or pfile.stem
                        print(
                            f"  [+] Found existing workspace matching path (ID: {pid})"
                        )
                        return pid
                except (ValueError, OSError):
                    continue

    # No existing project: generate new UUID and register
    project_id = str(uuid.uuid4())
    project_data = {
        "id": project_id,
        "name": "dreaming",
        "projectResources": {
            "resources": [
                {
                    "gitFolder": {
                        "folderUri": dreaming_dir.as_uri(),
                        "defaultBranch": "main",
                    }
                }
            ]
        },
        "settings": {},
        "isWorkspaceOnly": False,
    }
    project_file = projects_dir / f"{project_id}.json"
    _save_json(project_file, project_data)
    print(
        f"  [+] Registered new Antigravity project 'dreaming' at {project_file} (ID: {project_id})"
    )
    return project_id


def setup_dreamer(
    config_dir: Path | None = None,
    cron: str = DEFAULT_CRON,
    bootstrap: bool = False,
) -> None:
    """Execute complete automated setup for agy-dreamer."""
    if config_dir is None:
        config_dir = Path.home() / ".gemini" / "config"

    dreaming_dir = config_dir / "dreaming"

    print("=" * 70)
    print("agy-dreamer: Automated Setup & Sidecar Configuration")
    print("=" * 70)
    print(f"Global Config Dir: {config_dir}")
    print(f"Dreaming Root:     {dreaming_dir}")
    print()

    # 1. Scaffold directory structure
    print("[1/5] Scaffolding directory layout...")
    for sub in ["memories", "proposals", "archive"]:
        p = dreaming_dir / sub
        p.mkdir(parents=True, exist_ok=True)
        print(f"  [+] {p}")

    # Ensure baseline .state.json exists
    state_file = dreaming_dir / ".state.json"
    if not state_file.exists():
        initial_state = {
            "cold_start_completed": False,
            "turbo_mode": True,
            "processed_session_ids": [],
            "last_consolidated_timestamp": None,
            "last_consolidated_session_id": None,
            "total_invariants_extracted": 0,
        }
        _save_json(state_file, initial_state)
        print(f"  [+] Initialized state tracker at {state_file}")

    # 2. Register / resolve Antigravity project
    print("\n[2/5] Resolving Antigravity project workspace...")
    project_id = resolve_or_create_project(config_dir, dreaming_dir)

    # 3. Create Sidecar Scheduled Task definition
    print("\n[3/5] Creating scheduled sidecar definition...")
    sidecars_dir = config_dir / "sidecars" / "nightly-dreaming"
    sidecar_file = sidecars_dir / "sidecar.json"
    sidecar_data = {
        "builtin": "schedule",
        "restart_policy": "always",
        "args": [
            cron,
            "agentapi",
            "new-conversation",
            "--",
            DEFAULT_PROMPT,
        ],
        "display_name": "Nightly Dreaming",
    }
    _save_json(sidecar_file, sidecar_data)
    print(
        f"  [+] Sidecar task definition created at {sidecar_file} (Schedule: '{cron}')"
    )

    # 4. Enable plugin and sidecar in config.json
    print("\n[4/5] Enabling plugin and sidecar in config.json...")
    config_json_path = config_dir / "config.json"
    config_data = _load_json(config_json_path)

    plugins = config_data.setdefault("plugins", {})
    plugins["agy-dreamer"] = {"enabled": True}

    sidecars = config_data.setdefault("sidecars", {})
    sidecars["nightly-dreaming"] = {
        "enabled": True,
        "projectId": project_id,
    }
    _save_json(config_json_path, config_data)
    print(f"  [+] Updated {config_json_path}")
    print("      - Plugin 'agy-dreamer': ENABLED")
    print(
        f"      - Sidecar 'nightly-dreaming': ENABLED (Bound to Project: {project_id})"
    )

    # 5. Optional bootstrap cold-start
    if bootstrap:
        print("\n[5/5] Running immediate cold-start historical bootstrapping...")
        try:
            from scripts.cold_start import bootstrap_cold_start

            db_path = (
                Path.home() / ".gemini" / "antigravity" / "conversation_summaries.db"
            )
            if db_path.exists():
                summary = bootstrap_cold_start(
                    db_path=db_path,
                    config_dir=config_dir,
                    force=False,
                    dry_run=False,
                )
                print(
                    f"  [+] Bootstrapped {summary.get('clusters_formed', 0)} memory files across {summary.get('total_sessions_mapped', 0)} sessions."
                )
            else:
                print(
                    f"  [!] conversation_summaries.db not found at {db_path}. Skipping immediate bootstrap."
                )
        except (ImportError, OSError, RuntimeError, ValueError) as e:
            print(
                f"  [!] Bootstrap encountered an issue: {e}. Will run automatically on first scheduled run."
            )
    else:
        print(
            "\n[5/5] Cold-start ready (will run automatically on first scheduled trigger)."
        )

    print("\n" + "=" * 70)
    print("Setup Complete! Antigravity will autonomously run nightly dreaming.")
    print(f"   Schedule: {cron} (with automated jitter offset)")
    print("   Project:  ~/.gemini/config/dreaming")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-Click Setup for Antigravity agy-dreamer Plugin.",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="Custom path to ~/.gemini/config (defaults to standard home location)",
    )
    parser.add_argument(
        "--cron",
        type=str,
        default=DEFAULT_CRON,
        help=f"Custom cron expression for nightly consolidation (default: '{DEFAULT_CRON}')",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Run cold-start historical ingestion immediately after setup",
    )

    args = parser.parse_args()
    setup_dreamer(
        config_dir=args.config_dir,
        cron=args.cron,
        bootstrap=args.bootstrap,
    )


if __name__ == "__main__":
    main()
