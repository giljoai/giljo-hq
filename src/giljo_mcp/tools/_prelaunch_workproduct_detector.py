# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    try:
        if project.ever_launched_at is not None or not git_commits:
            return

        from giljo_mcp.services.notification_service import NotificationService

        project_id = str(project.id)
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
            body=(
                f"{label} was closed out with {commits_phrase} recorded, but it "
                "never passed the in-app Implement click. This usually just means "
                "its agents ran headless against Giljo HQ, or you closed it "
                "from the CLI -- the work was saved either way. Open it to review "
                "what was recorded."
            ),
            dedupe_key=f"project.pre_launch_workproduct:{project_id}",
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
