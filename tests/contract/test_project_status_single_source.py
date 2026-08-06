# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Single-source-of-truth guard for the ``ProjectStatus`` enum (BE-5039).

Repurposed from the original cross-layer drift test
(``test_status_enum_consistency.py``) per design Decision 5.

Failure mode this test guards against
-------------------------------------
A future contributor re-introduces a hardcoded list of project status
literals somewhere in ``src/giljo_mcp/`` or ``api/``. After BE-5039, the
canonical source is :class:`giljo_mcp.domain.project_status.ProjectStatus`;
duplicating the six values in another file is the regression we want to
catch.

What this test actually checks
------------------------------
1. The Python enum has exactly the six canonical members in the
   canonical order. Reordering or extending the enum without an
   accompanying migration is a regression.
2. The legacy module-level constants
   (``IMMUTABLE_PROJECT_STATUSES``, ``LIFECYCLE_FINISHED_STATUSES``,
   ``VALID_PROJECT_STATUSES``) re-exported from
   ``giljo_mcp.services.project_service`` resolve to the same
   ``frozenset[ProjectStatus]`` values exposed by
   ``giljo_mcp.domain.project_status``. They are aliases now -- if
   someone re-defines them locally with a literal, this test catches it.
3. The migration ``ce_0008_project_status_enum`` declares the same six
   values in the same order as the Python enum. Drift here would crash
   ``alembic upgrade head`` on fresh installs.

Notes
-----
- Frontend ``StatusBadge.vue`` validation is the implementer-frontend's
  Phase 4 scope. They will add a frontend-side assertion in this same
  test once the StatusBadge stops carrying a hardcoded literal.
"""

from __future__ import annotations

import re
from pathlib import Path

from giljo_mcp.domain.project_status import (
    IMMUTABLE_PROJECT_STATUSES as DOMAIN_IMMUTABLE,
)
from giljo_mcp.domain.project_status import (
    LIFECYCLE_FINISHED_STATUSES as DOMAIN_LIFECYCLE_FINISHED,
)
from giljo_mcp.domain.project_status import (
    VALID_PROJECT_STATUSES as DOMAIN_VALID,
)
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.services.project_service import (
    IMMUTABLE_PROJECT_STATUSES as SERVICE_IMMUTABLE,
)
from giljo_mcp.services.project_service import (
    LIFECYCLE_FINISHED_STATUSES as SERVICE_LIFECYCLE_FINISHED,
)
from giljo_mcp.services.project_service import (
    VALID_PROJECT_STATUSES as SERVICE_VALID,
)


# Repo root is two parents up from this file: tests/contract/<this>.py
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _REPO_ROOT / "migrations" / "versions" / "ce_0008_project_status_enum.py"


_CANONICAL_ORDER: list[str] = [
    "inactive",
    "active",
    "completed",
    "cancelled",
    "terminated",
    "deleted",
    # BE-9157: superseded is appended LAST (matches the Postgres ENUM append
    # order from ce_0078's ``ALTER TYPE ... ADD VALUE``). ce_0008 (the original
    # CREATE TYPE, still asserted below) declared only the first six.
    "superseded",
    # IMP-9258: parked is appended after superseded (ce_0083's
    # ``ALTER TYPE ... ADD VALUE``).
    "parked",
]


def test_enum_has_exactly_canonical_members_in_order() -> None:
    """The enum is fixed at the canonical members in canonical order."""

    assert [s.value for s in ProjectStatus] == _CANONICAL_ORDER


def test_service_constants_are_aliases_of_domain_constants() -> None:
    """``project_service`` re-exports the domain constants verbatim.

    If someone replaces the import with a locally redefined literal
    (frozenset of strings), the identity-equality check below fails.
    """

    assert SERVICE_IMMUTABLE is DOMAIN_IMMUTABLE
    assert SERVICE_LIFECYCLE_FINISHED is DOMAIN_LIFECYCLE_FINISHED
    assert SERVICE_VALID is DOMAIN_VALID


def test_migration_declares_same_enum_values_in_canonical_order() -> None:
    """The Alembic migration declares the same six values, same order."""

    assert _MIGRATION.is_file(), f"Migration file not found at {_MIGRATION}"

    text = _MIGRATION.read_text(encoding="utf-8")

    # Pattern matches the CREATE TYPE ... AS ENUM (...) literal regardless
    # of inline whitespace. We require the canonical six in canonical
    # order so any future reorder shows up here as a test failure.
    pattern = re.compile(
        r"CREATE\s+TYPE\s+project_status\s+AS\s+ENUM\s*\(\s*"
        r"'inactive'\s*,\s*"
        r"'active'\s*,\s*"
        r"'completed'\s*,\s*"
        r"'cancelled'\s*,\s*"
        r"'terminated'\s*,\s*"
        r"'deleted'\s*\)",
        re.IGNORECASE | re.DOTALL,
    )
    assert pattern.search(text), (
        f"Migration {_MIGRATION.name} no longer declares the canonical six values "
        "in canonical order. If you reordered the enum, also reorder the "
        "ProjectStatus class declaration in src/giljo_mcp/domain/project_status.py "
        "and update this test."
    )
