# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _REPO_ROOT / "migrations" / "versions" / "ce_0008_project_status_enum.py"


_CANONICAL_ORDER: list[str] = [
    "inactive",
    "active",
    "completed",
    "cancelled",
    "terminated",
    "deleted",
    "superseded",
    "parked",
]


def test_enum_has_exactly_canonical_members_in_order() -> None:

    assert [s.value for s in ProjectStatus] == _CANONICAL_ORDER


def test_service_constants_are_aliases_of_domain_constants() -> None:

    assert SERVICE_IMMUTABLE is DOMAIN_IMMUTABLE
    assert SERVICE_LIFECYCLE_FINISHED is DOMAIN_LIFECYCLE_FINISHED
    assert SERVICE_VALID is DOMAIN_VALID


def test_migration_declares_same_enum_values_in_canonical_order() -> None:

    assert _MIGRATION.is_file(), f"Migration file not found at {_MIGRATION}"

    text = _MIGRATION.read_text(encoding="utf-8")

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
