# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9085 -- closeout-hook detector for a pre-launch work-product skip.

Extracted out of ``write_memory_entry.py`` (INF-6132-style split) to keep
that file under the 800-line guardrail; this module has exactly one caller
(``write_360_memory``'s ``project_completion`` closeout path).
"""

from __future__ import annotations

import logging
from typing import Any

from giljo_mcp.database import DatabaseManager


logger = logging.getLogger(__name__)


async def check_and_emit_prelaunch_workproduct(
    db_manager: DatabaseManager,
    tenant_key: str,
    project: Any,
    git_commits: list,
) -> None:
    """BE-9085: alarm-only detector for a closeout with commits but no launch.

    Fires an operator-visible NotificationService banner when a
    ``project_completion`` closeout carries git commits while
    ``project.ever_launched_at`` is still NULL -- the human Implement-gate
    approval was never crossed at any point in this project's life. This is
    an ALARM, not a lock: the entire detect+emit runs inside this
    try/except so a detection or notification failure can never fail,
    delay, or alter the closeout (the 360 memory entry is already written
    and flushed by the time this runs). Any exception here is logged and
    swallowed.

    Closeout-hook only (INF-5076): commits reach the server only at
    closeout by design; an agent/orchestrator that never closes out through
    this tool stays invisible to this detector -- accepted, see BE-9085
    project notes.

    Restage false-positive -- FIXED (BE-9085b): ``restage`` clears
    ``implementation_launched_at`` back to NULL as a clean-slate reset for
    the next impl cycle (see ``project_staging_service.py`` restage), but it
    deliberately does NOT clear the durable ``ever_launched_at`` set-once
    signal. A project that WAS launched, produced legitimate commits, then
    was restaged and later closed out without re-launching still has
    ``ever_launched_at`` set, so this detector correctly SUPPRESSES the
    alarm for that case now. ``ever_launched_at`` is cleared only by
    ``reset_to_prestage`` (the discard-everything rewind), which genuinely
    returns the project to birth.
    """
    try:
        if project.ever_launched_at is not None or not git_commits:
            return

        from giljo_mcp.services.notification_service import NotificationService

        project_id = str(project.id)
        # taxonomy_alias is a SELECT-time column_property already loaded on the
        # ORM instance (zero extra queries); may be None for a project without a
        # resolvable tag. Lead the human-facing copy with it when present.
        alias = getattr(project, "taxonomy_alias", None)
        label = f"{alias} — {project.name}" if alias else project.name
        commit_count = len(git_commits)
        commits_phrase = f"{commit_count} commit{'s' if commit_count != 1 else ''}"

        service = NotificationService(db_manager=db_manager)
        await service.upsert_by_dedupe_key(
            tenant_key=tenant_key,
            user_id=None,
            notification_type="project.pre_launch_workproduct",
            severity="warning",
            title=f"{label}: recorded without an Implement click",
            # Informational, not error-toned: this event usually just means the
            # project's agents ran headless against Giljo HQ, or it was closed
            # from the CLI -- both authorized. The work was recorded; it simply
            # never passed the in-app Implement click.
            body=(
                f"{label} was closed out with {commits_phrase} recorded, but it "
                "never passed the in-app Implement click. This usually just means "
                "its agents ran headless against Giljo HQ, or you closed it "
                "from the CLI -- the work was saved either way. Open it to review "
                "what was recorded."
            ),
            dedupe_key=f"project.pre_launch_workproduct:{project_id}",
            # FE-9229: the bell, NOT the banner. This row was previously emitted
            # with surface="banner", but SystemStatusBanner renders only its
            # ALLOWED_TYPES allowlist of singleton ``system.*`` state -- a
            # ``project.*`` row is silently discarded there, so the notification
            # rendered on no surface it was addressed to. It stayed reachable in
            # the bell only because the bell ignores ``surface`` entirely, which
            # is an accident rather than a contract. The bell is also the right
            # home on the merits: this fires once PER PROJECT, so a headless
            # chain of N closeouts would stack N sticky banners, and the bell
            # already deep-links the row to its project.
            surface="bell",
            cta_label="Review project",
            cta_route="Projects",
            dismissible=True,
            payload={
                "project_id": project_id,
                "project_name": project.name,
                "taxonomy_alias": alias,
                "commit_count": commit_count,
            },
        )
    except Exception as detect_err:  # noqa: BLE001 -- fail-open by design (BE-9085)
        logger.warning(
            "BE-9085 pre-launch workproduct detection skipped (fail-open): %s",
            detect_err,
            exc_info=True,
        )
