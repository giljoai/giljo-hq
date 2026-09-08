# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Canonical ``ProjectStatus`` enum + class-level metadata (BE-5039).

Single Source of Truth for project status across the backend, the
Postgres ENUM ``project_status`` (created by migration
``ce_0008_project_status_enum``), and the frontend metadata API at
``GET /api/v1/project-statuses/``.

Design reference: BE-5039 project-status single-source-of-truth design
(commit 0c69ab13c).

Goals
-----
* One declaration site for the canonical project statuses
  (``inactive``, ``active``, ``completed``, ``cancelled``, ``terminated``,
  ``deleted``, ``superseded``, ``parked``).
* Class-level metadata (label, color token, lifecycle flags) so the
  frontend can pull the same metadata via API and gate writes against
  the same flags the backend uses.
* Derived sets replace the legacy module-level constants in
  ``giljo_mcp.services.project_service`` (``IMMUTABLE_PROJECT_STATUSES``,
  ``LIFECYCLE_FINISHED_STATUSES``, ``VALID_PROJECT_STATUSES``,
  ``_VALID_UPDATE_STATUSES``).

Edition isolation
-----------------
This module is CE-foundational. SaaS does not extend it. If SaaS ever
needs a SaaS-only status, it adds the value here in CE with metadata
declaring it SaaS-scoped -- cross-edition status divergence at the
schema level is forbidden because it would either crash the export
script's SaaS-table-reference check or break ``alembic upgrade head``
on fresh CE installs.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectStatusMeta:
    """Presentation + gating metadata for a single :class:`ProjectStatus` member.

    Attributes
    ----------
    label
        Human-readable badge label rendered by the frontend
        ``StatusBadge.vue`` component.
    color_token
        Name of a SCSS custom property declared in
        ``frontend/src/styles/design-tokens.scss``. The frontend resolves
        the token at runtime via ``getComputedStyle(...).getPropertyValue``
        rather than embedding hex literals here -- this keeps the
        Luminous Pastel palette as the single source of color truth and
        keeps the enum semantically pure (color is presentation, not
        domain data).
    is_lifecycle_finished
        Members of ``LIFECYCLE_FINISHED_STATUSES`` -- the read-side
        default exclusion bucket for ``list_projects_for_mcp`` when no
        explicit status filter is supplied.
    is_immutable
        Members of ``IMMUTABLE_PROJECT_STATUSES`` -- write gate.
        Projects in these states reject ``update_project()`` writes
        unless the caller is using a dedicated lifecycle endpoint.
    is_user_mutable_via_mcp
        Members of ``VALID_UPDATE_STATUSES`` -- whitelist of statuses an
        MCP tool may pass to ``update_project_metadata``. Excludes
        ``terminated`` and ``deleted`` because those are reachable only
        via the dedicated lifecycle endpoints (``archive_project`` /
        ``delete_project``).
    """

    label: str
    color_token: str
    is_lifecycle_finished: bool
    is_immutable: bool
    is_user_mutable_via_mcp: bool


class ProjectStatus(enum.StrEnum):
    """Canonical project lifecycle status.

    Inherits from :class:`str` so equality with raw strings is preserved
    (``ProjectStatus.ACTIVE == "active"`` is ``True``). This keeps every
    legacy ``project.status == "active"`` comparison working unchanged
    after the migration -- callers can adopt the enum at their own pace.

    Order of declaration matches the canonical ENUM order in the
    Postgres type ``project_status``; do not reorder without a migration.
    """

    INACTIVE = "inactive"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    TERMINATED = "terminated"
    DELETED = "deleted"
    # BE-9157: a project whose work was replaced by a successor project (audit
    # trail for consolidated/duplicate roadmap items). Declared LAST to match the
    # Postgres ENUM order — ce_0078 appends it via ``ALTER TYPE ... ADD VALUE``,
    # which always adds to the end. Do not reorder without a migration.
    SUPERSEDED = "superseded"
    # IMP-9258: a project set aside without cancelling it -- hidden from the
    # canned roadmap plan (own exclusion, NOT lumped into
    # LIFECYCLE_FINISHED_STATUSES) but fully resumable: NOT immutable, so the
    # generic update_project() write path can unpark it straight back to
    # inactive/active with no dedicated restore endpoint needed (unlike
    # cancelled, which IS immutable and requires the separate restore flow).
    # Declared LAST to match the Postgres ENUM order -- ce_0083 appends it via
    # ``ALTER TYPE ... ADD VALUE``, which always adds to the end. Do not
    # reorder without a migration.
    PARKED = "parked"

    @property
    def meta(self) -> ProjectStatusMeta:
        """Return the :class:`ProjectStatusMeta` registered for this member."""

        return PROJECT_STATUS_META[self]

    @property
    def label(self) -> str:
        """Human-readable badge label."""

        return self.meta.label

    @property
    def color_token(self) -> str:
        """Name of the SCSS color token (no hex literal)."""

        return self.meta.color_token

    @property
    def is_lifecycle_finished(self) -> bool:
        """Whether this status is a "closed" lifecycle state."""

        return self.meta.is_lifecycle_finished

    @property
    def is_immutable(self) -> bool:
        """Whether this status blocks generic ``update_project()`` writes."""

        return self.meta.is_immutable

    @property
    def is_user_mutable_via_mcp(self) -> bool:
        """Whether MCP tools may pass this value to ``update_project_metadata``."""

        return self.meta.is_user_mutable_via_mcp


# Class-level metadata. The dict is the single registration site; the derived
# sets below are computed once at import time. Keeping all metadata in one
# literal -- rather than spread across enum-member docstrings or a config
# loader -- is a deliberate readability choice for a six-row enum.
PROJECT_STATUS_META: dict[ProjectStatus, ProjectStatusMeta] = {
    ProjectStatus.INACTIVE: ProjectStatusMeta(
        label="Inactive",
        color_token="color-text-muted",
        is_lifecycle_finished=False,
        is_immutable=False,
        is_user_mutable_via_mcp=True,
    ),
    ProjectStatus.ACTIVE: ProjectStatusMeta(
        label="Active",
        color_token="color-agent-implementer",
        is_lifecycle_finished=False,
        is_immutable=False,
        is_user_mutable_via_mcp=True,
    ),
    ProjectStatus.COMPLETED: ProjectStatusMeta(
        label="Completed",
        color_token="color-status-complete",
        is_lifecycle_finished=True,
        is_immutable=True,
        is_user_mutable_via_mcp=True,
    ),
    ProjectStatus.CANCELLED: ProjectStatusMeta(
        label="Cancelled",
        color_token="color-status-blocked",
        is_lifecycle_finished=True,
        is_immutable=True,
        is_user_mutable_via_mcp=True,
    ),
    ProjectStatus.TERMINATED: ProjectStatusMeta(
        label="Terminated",
        color_token="color-agent-analyzer",
        is_lifecycle_finished=True,
        is_immutable=False,
        is_user_mutable_via_mcp=False,
    ),
    ProjectStatus.DELETED: ProjectStatusMeta(
        label="Deleted",
        color_token="color-agent-analyzer",
        is_lifecycle_finished=True,
        is_immutable=False,
        is_user_mutable_via_mcp=False,
    ),
    # BE-9157: superseded is a CLOSED lifecycle state (work moved to a successor),
    # so it is lifecycle-finished -> hidden from the default agent list view and
    # skipped by 360-context fetches, and immutable -> no further generic
    # update_project() metadata writes once replaced (matches completed/cancelled).
    # BE-9499b: is_user_mutable_via_mcp=True -- the MCP update_project tool now
    # carries successor_project_id (VALID_UPDATE_STATUSES gates the raw status
    # VALUE, not the pointer; the pointer requirement is enforced separately by
    # ProjectService.update_project, which refuses status='superseded' with no
    # successor -- or an ineligible one -- as SUPERSEDE_REQUIRES_SUCCESSOR before
    # this status ever reaches the row). is_immutable stays True: "reachable FROM
    # mcp" and "accepts further writes once superseded" are separate properties --
    # flipping this flag does not weaken that one.
    # FE-9508: color_token was color-text-muted, identical to INACTIVE -- the worst
    # available collision (not-started-yet vs replaced-and-finished-forever wearing
    # the same pill). Operator ruling 2026-08-26: use color-agent-orchestrator
    # (tan, #d4b08a, WCAG 7.48:1). Pink was rejected (already means failure via
    # color-status-failed); mint green was rejected (already means completed).
    # Known/accepted trade-off: tan is also the orchestrator AGENT colour -- free
    # among project STATUSES, which is the collision that matters. Do not invent a
    # new palette token to avoid this.
    ProjectStatus.SUPERSEDED: ProjectStatusMeta(
        label="Superseded",
        color_token="color-agent-orchestrator",
        is_lifecycle_finished=True,
        is_immutable=True,
        is_user_mutable_via_mcp=True,
    ),
    # IMP-9258: parked is a deliberate two-way door -- NOT lifecycle-finished
    # (stays visible in default project lists / list_projects, unlike
    # completed/cancelled/terminated/deleted/superseded) and NOT immutable (so
    # a plain update_project(status='active'|'inactive') un-parks it through
    # the same generic write path -- no dedicated restore endpoint required,
    # unlike cancelled). is_user_mutable_via_mcp=True: an agent can park/unpark
    # via update_project(status='parked') directly. color-agent-reviewer
    # (Lavender) is not used by any other project status, keeping the badge
    # visually distinct; the frontend may re-map this token when it wires the
    # UI (IMP-9258 P2).
    ProjectStatus.PARKED: ProjectStatusMeta(
        label="Parked",
        color_token="color-agent-reviewer",
        is_lifecycle_finished=False,
        is_immutable=False,
        is_user_mutable_via_mcp=True,
    ),
}


# Sanity check: every enum member must carry metadata. Catches reorder /
# rename drift at import time rather than at first .meta lookup.
if set(PROJECT_STATUS_META.keys()) != set(ProjectStatus):
    missing = set(ProjectStatus) - set(PROJECT_STATUS_META.keys())
    extra = set(PROJECT_STATUS_META.keys()) - set(ProjectStatus)
    raise RuntimeError(
        f"PROJECT_STATUS_META drift detected. Missing metadata: {missing}. "
        f"Extra metadata: {extra}. Update giljo_mcp.domain.project_status."
    )


# Derived sets -- replace the legacy module-level constants in
# giljo_mcp.services.project_service. Each derived set is a frozenset of
# ProjectStatus members; equality with raw strings still works because the
# enum inherits from str (e.g. ``"completed" in IMMUTABLE_PROJECT_STATUSES``
# is True).
IMMUTABLE_PROJECT_STATUSES: frozenset[ProjectStatus] = frozenset(
    s for s, m in PROJECT_STATUS_META.items() if m.is_immutable
)
LIFECYCLE_FINISHED_STATUSES: frozenset[ProjectStatus] = frozenset(
    s for s, m in PROJECT_STATUS_META.items() if m.is_lifecycle_finished
)
VALID_UPDATE_STATUSES: frozenset[ProjectStatus] = frozenset(
    s for s, m in PROJECT_STATUS_META.items() if m.is_user_mutable_via_mcp
)
VALID_PROJECT_STATUSES: frozenset[ProjectStatus] = frozenset(ProjectStatus)
