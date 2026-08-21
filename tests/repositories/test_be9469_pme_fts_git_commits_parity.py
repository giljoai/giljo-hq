# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9469 -- turn the FTS document/index parity CONTRACT into a MECHANISM.

``ce_0052_pme_fts_be6082.py`` documented "the runtime ``_FTS_DOCUMENT_SQL``
string MUST stay byte-identical to the index's indexed expression" as a
COMMENT. A comment is prose, not a mechanism (house rule: mechanism vs prose)
-- nothing stopped the two from drifting except a reader noticing. BE-9469 is
the first change to either side since ce_0052 shipped (widening the document
to include ``git_commits``, paired with ``ce_0096_pme_fts_git_commits_be9469.py``
recreating ``idx_pme_fts`` over the same wider expression). This test is what
stops the SECOND person from changing only one side.

Loads both modules' string constants directly (no scratch DB needed -- this is
a pure string-equality check, not a schema test) so neither can be edited
without this test seeing it:
- ``src/giljo_mcp/repositories/product_memory_repository.py::_FTS_DOCUMENT_SQL``
  (the live query expression)
- ``migrations/versions/ce_0096_pme_fts_git_commits_be9469.py::_FTS_DOCUMENT``
  (the CURRENT index-defining migration -- ce_0052's own ``_FTS_DOCUMENT`` is
  intentionally NOT compared here; it is superseded history, kept only so
  ce_0096's downgrade can restore it verbatim).

Edition Scope: Both.
"""

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
    """The widened document must be additive over ce_0052's original -- the new
    field appended, nothing removed or reordered (byte-prefix check)."""
    assert _migration._FTS_DOCUMENT.startswith(_migration._FTS_DOCUMENT_ORIGINAL[:-1]), (
        "the widened FTS document does not extend the original document as a prefix -- "
        "an existing field may have been dropped or reordered, not just widened"
    )
    assert "git_commits" in _migration._FTS_DOCUMENT
    assert "git_commits" not in _migration._FTS_DOCUMENT_ORIGINAL
