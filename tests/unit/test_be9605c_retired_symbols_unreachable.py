# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_TREES = ("src", "api", "frontend/src", "internal", "scripts", "installer")
_SKIP_DIRS = {"node_modules", "__pycache__", ".venv", "dist", "tests", "__tests__"}
_SUFFIXES = {".py", ".js", ".vue", ".ts", ".sh", ".ps1", ".md", ".toml", ".json", ".yml", ".yaml"}

_RETIRED = (
    "agent_template_assembler",
    "install_targets",
    "render_claude_agent",
    "render_codex_agent",
    "render_opencode_agent",
    "render_generic_agent",
    "select_templates_for_packaging",
    "stage_agent_templates",
    "stage_combined_setup",
    "staged_agent_zip_is_stale",
    "agent-templates.zip",
    "agent_templates.zip",
    "install_agent_templates",
    "active_product_export_timestamps",
    "get_export_timestamps_for_product",
    "record_product_export",
    "build_export_context",
    "mark_templates_exported",
    "update_exported_timestamps",
    "effective_last_exported_at",
    "may_be_stale",
    "setup:agents_downloaded",
    "setup_agents_downloaded",
    "AgentsDownloaded",
    "Agents only",
    "list_agent_templates",
    "OWNERSHIP_MARKER_TOKEN",
    "build_agent_install_block",
)

_RETIRED_AGENT_DIRS = (
    ".claude/agents/",
    ".codex/agents/",
    ".opencode/agents/",
)

_AGENT_DIR_ALLOWED = {
    "src/giljo_mcp/services/mission_assembly.py",
}

_DROPPED_COLUMNS = ("last_exported_at", "user_managed_export")

_MIGRATION_ALLOWED = {
    "migrations/versions/baseline_v37_unified.py",
    "migrations/versions/ce_0081_download_tokens_staged_at.py",
    "migrations/versions/ce_0094_per_product_export_staleness.py",
    "migrations/versions/ce_0105_db9607_drop_template_export_columns.py",
}

_MIGRATION_REQUIRED = {
    "migrations/versions/baseline_v37_unified.py",
    "migrations/versions/ce_0094_per_product_export_staleness.py",
    "migrations/versions/ce_0105_db9607_drop_template_export_columns.py",
}


def _files():
    for tree in _TREES:
        base = _ROOT / tree
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in _SUFFIXES:
                continue
            if _SKIP_DIRS & set(path.relative_to(_ROOT).parts):
                continue
            if tree == "internal" and path.suffix not in {".py", ".sh", ".yml", ".yaml"}:
                continue
            if path.name.endswith((".spec.js", ".test.js")):
                continue
            yield path


def _hits(needles, allowed=()):
    pattern = re.compile("|".join(re.escape(n) for n in needles))
    found = []
    for path in _files():
        rel = path.relative_to(_ROOT).as_posix()
        if rel in allowed or rel.startswith("migrations/"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = pattern.search(line)
            if m:
                found.append(f"{rel}:{i}: {m.group(0)}")
    return found


def test_retired_symbols_have_zero_callers():
    hits = _hits(_RETIRED)
    assert hits == [], "retired install-path references survive:\n" + "\n".join(hits)


def test_dropped_export_columns_have_zero_references():
    hits = _hits(_DROPPED_COLUMNS)
    assert hits == [], "dropped export-tracking columns still referenced:\n" + "\n".join(hits)


def test_dropped_export_columns_appear_only_in_their_own_migration_history():
    pattern = re.compile("|".join(re.escape(n) for n in _DROPPED_COLUMNS))
    seen = set()
    for path in (_ROOT / "migrations").rglob("*.py"):
        rel = path.relative_to(_ROOT).as_posix()
        if rel.startswith("migrations/archive/") or "__pycache__" in rel:
            continue
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            seen.add(rel)
    assert seen <= _MIGRATION_ALLOWED, (
        f"a migration outside the DB-9607 history names a dropped export column: {sorted(seen - _MIGRATION_ALLOWED)}"
    )
    assert seen >= _MIGRATION_REQUIRED, (
        "a revision that must name these columns no longer does -- the drop or the "
        f"history it rests on has gone missing: {sorted(_MIGRATION_REQUIRED - seen)}"
    )


@pytest.mark.parametrize(
    "module",
    ["giljo_mcp.tools.agent_template_assembler", "giljo_mcp.install_targets"],
)
def test_retired_modules_do_not_import(module):
    with pytest.raises(ModuleNotFoundError):
        __import__(module)


def test_retired_installer_scripts_are_gone():
    for name in ("install_agent_templates.sh", "install_agent_templates.ps1"):
        assert not (_ROOT / "installer" / "templates" / name).exists(), name


def test_retired_agent_directories_are_not_named_in_agent_facing_prose():
    hits = _hits(_RETIRED_AGENT_DIRS, allowed=_AGENT_DIR_ALLOWED)
    assert hits == [], "agent-facing prose still points at a retired agent-definition directory:\n" + "\n".join(hits)
