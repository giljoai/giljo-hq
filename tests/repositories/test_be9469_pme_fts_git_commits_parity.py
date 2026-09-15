# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import importlib.util
from pathlib import Path

from giljo_mcp.repositories.product_memory_repository import _FTS_DOCUMENT_SQL


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REV = "ce_0096_pme_fts_git_commits_be9469"
_MIGRATION_PATH = PROJECT_ROOT / "migrations" / "versions" / f"{_REV}.py"

_spec = importlib.util.spec_from_file_location(_REV, _MIGRATION_PATH)
_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration)


def test_repository_fts_document_is_byte_identical_to_the_migrations_current_index_expression():
    assert _FTS_DOCUMENT_SQL == _migration._FTS_DOCUMENT, (
        "product_memory_repository._FTS_DOCUMENT_SQL has drifted from "
        f"{_REV}.py's _FTS_DOCUMENT -- idx_pme_fts no longer matches the runtime query "
        "expression, so Postgres silently stops using the index for memory search "
        "(correct results, quietly no index). Whichever side you just edited, edit "
        "the other one too."
    )


def test_migration_git_commits_document_widens_but_does_not_drop_the_original_fields():
    assert _migration._FTS_DOCUMENT.startswith(_migration._FTS_DOCUMENT_ORIGINAL[:-1]), (
        "the widened FTS document does not extend the original document as a prefix -- "
        "an existing field may have been dropped or reordered, not just widened"
    )
    assert "git_commits" in _migration._FTS_DOCUMENT
    assert "git_commits" not in _migration._FTS_DOCUMENT_ORIGINAL
