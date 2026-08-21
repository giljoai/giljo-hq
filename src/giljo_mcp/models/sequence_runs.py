# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SequenceRun model — durable state machine for the Sequential Multi-Project Runner.

Persists a multi-project sequential run so the main orchestrator A can resume
from ``current_index`` after a crash or context compaction, without re-staging
projects already handled.

Edition Scope: CE. Matching migration: ``migrations/versions/ce_0058_sequence_runs``.
"""

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from giljo_mcp.platform_registry import ACCEPTED_EXECUTION_MODES, VALID_EXECUTION_MODES

from .base import Base, generate_uuid


# Enum-like membership sets validated at the write boundary (SequenceRunService).

# terminated = graceful conductor-driven exit; cancelled = hard administrative reset (BE-6165b).
VALID_RUN_STATUSES: frozenset[str] = frozenset(
    {"pending", "running", "completed", "stalled", "failed", "terminated", "cancelled"}
)

# terminated = the in-flight project at a graceful chain terminate (BE-6165b). `released`
# (a downstream project freed from the run) is modeled as drop-out-of-run, NOT a status value.
VALID_PROJECT_STATUSES: frozenset[str] = frozenset(
    {"pending", "staged", "implementing", "awaiting_review", "completed", "failed", "stalled", "terminated"}
)

# BE-9000k: the ONE terminal-status set for a chain member — a project that has
# reached a terminal state releases the conductor's complete_job guard. WIDE set
# (2026-07-02): failed / cancelled DO release, so a member ending
# failed/cancelled never wedges the conductor forever. Single source of truth
# imported by job_completion_service, sequence_run_service, and project_helpers.
# Home: models (the sequence-run domain), beside the other status frozensets —
# a service-module home would force project_helpers into a module-level
# service->service import it was explicitly built to avoid.
# NOTE: "cancelled" is currently unreachable at MEMBER level — per-member statuses
# are membership-validated against VALID_PROJECT_STATUSES (no "cancelled"; only the
# RUN-level status can be cancelled). Included here so run-level tooling and any
# future member-cancel path share one definition; do not assume a member row can
# carry it today (capstone note, 2026-07-02).
CHAIN_TERMINAL_PROJECT_STATUSES: frozenset[str] = frozenset({"completed", "terminated", "cancelled", "failed"})

VALID_REVIEW_POLICIES: frozenset[str] = frozenset({"per_card", "auto_close"})

# BE-6165d: Single source of truth imported from PlatformRegistry so a new platform
# row is automatically accepted here without a parallel frozenset edit.
# BE-9035c: ACCEPTED_EXECUTION_MODES is the boundary set (2 canonical modes + 5 legacy
# aliases) — sequence-run create/update validate against it so a stored legacy
# ``*_cli`` run never hard-fails. VALID_EXECUTION_MODES stays the 2-mode NEW-write set.
# Exported for backwards-compat callers that import these from this module.
__all__ = ["ACCEPTED_EXECUTION_MODES", "VALID_EXECUTION_MODES"]

# Hard cap enforced at the service layer (spec §1 locked decision #9).
MAX_SEQUENCE_PROJECTS: int = 5


class SequenceRun(Base):
    """Durable state machine for a multi-project sequential run."""

    __tablename__ = "sequence_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)

    # Ordered list of project_id strings the user selected.
    project_ids = Column(JSONB, nullable=False)

    # Topologically/roadmap-resolved run order (list of project_id strings).
    resolved_order = Column(JSONB, nullable=False)

    # 0-based index of the project currently being processed. Persisted so A
    # resumes here after a crash instead of restarting from 0.
    current_index = Column(Integer, nullable=False, default=0)

    # Uniform execution mode for the whole sequence. Values from _STAGE_MODE_MAP:
    # multi_terminal, claude_code_cli, codex_cli, gemini_cli, antigravity_cli.
    execution_mode = Column(String(50), nullable=False)

    # Run lifecycle status: pending / running / completed / stalled / failed /
    # terminated / cancelled. Flips pending->running the first time any member
    # crosses staging->implementation (project_helpers.advance_chain_member_to_
    # implementing, TSK-9091). "completed" is a defined-but-unreached value: a
    # finished run is PURGED (SequenceRunService.purge_run, BE-6189 Option A)
    # rather than ever having "completed" written to it.
    status = Column(String(30), nullable=False, default="pending")

    # Review policy: per_card (default) or auto_close.
    review_policy = Column(String(30), nullable=False, default="per_card")

    # Edit lock (FE-6171). false = Editing tier (membership/tickboxes editable);
    # true = Staged tier (Stage pressed -> tickboxes locked on all panes). Unstage
    # flips it back to false. Once the run is ultralocked (running, or a member
    # reached staging_complete) the service refuses to flip it false or edit
    # membership -- see SequenceRunService. Migration: ce_0064 (CE chain).
    locked = Column(Boolean, nullable=False, server_default="false", default=False)

    # Per-project status map: {project_id -> status_string}.
    # Values from VALID_PROJECT_STATUSES.
    project_statuses = Column(JSONB, nullable=False, default=dict)

    # BE-9098: durable per-member review acknowledgment. Ordered/deduped list of
    # member project_id strings the user has reviewed on a chain run. Persisting
    # this is what makes the "Review" badge survive refresh/navigation (it was
    # client-only before, wiped every page load). Append-only via
    # SequenceRunService.mark_member_reviewed; NEVER gates chain advancement or
    # purge_run (those key on CHAIN_TERMINAL_PROJECT_STATUSES). Non-null with a
    # '[]' server default so pre-column rows self-heal without a backfill.
    # Migration: ce_0077 (CE chain).
    reviewed_project_ids = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)

    # Cross-project chain plan the dedicated (project-less) conductor owns
    # (BE-6185). There is no head-project mission to reuse, so this is the
    # storage cell. User-EDITABLE before Implement; the SequenceRunService write
    # boundary REFUSES edits once the run is ultralocked, making it read-only
    # after Implement. NULL on solo / not-yet-populated runs. Migration: ce_0065.
    chain_mission = Column(Text, nullable=True)

    # Conductor identity (BE-6165b). NULL until the sequence driver self-registers the
    # head-of-order orchestrator on its first staging/mission call (BE-6165c). The
    # ChainDirectiveComposer reads these to address directives; NULL renders dormant.
    conductor_agent_id = Column(String(64), nullable=True)  # BE-9214: agent ids validate to 64
    conductor_project_id = Column(String(36), nullable=True)
    conductor_label = Column(String(80), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_sequence_runs_tenant", "tenant_key"),
        # TSK-9076: backup watermark sweep — MAX(updated_at) per tenant.
        Index("idx_sequence_runs_tenant_updated", "tenant_key", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<SequenceRun(id={self.id}, status={self.status}, index={self.current_index})>"
