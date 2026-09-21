# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any

from giljo_mcp.exceptions import (
    ProjectStateError,
    ResourceNotFoundError,
)
from giljo_mcp.models.sequence_runs import (
    CHAIN_TERMINAL_PROJECT_STATUSES,
    CHAIN_UNSTARTED_PROJECT_STATUSES,
)


class SequenceRunBackoutMixin:

    async def stop_chain(
        self,
        *,
        run_id: str,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        from giljo_mcp.services.project_service import ProjectService

        run = await self.get(run_id=run_id, tenant_key=tenant_key)
        member_ids: list[str] = run.get("resolved_order") or run.get("project_ids") or []
        member_statuses: dict[str, str] = run.get("project_statuses") or {}

        proj_svc = ProjectService(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            test_session=self._session,
        )

        healed: dict[str, str] = {}
        for pid in member_ids:
            member_status = member_statuses.get(pid) or ""
            if member_status in CHAIN_TERMINAL_PROJECT_STATUSES:
                continue
            try:
                if member_status in CHAIN_UNSTARTED_PROJECT_STATUSES:
                    await proj_svc.lifecycle.deactivate_project(pid, tenant_key=tenant_key)
                else:
                    await proj_svc.lifecycle.terminate_project(pid, tenant_key=tenant_key)
                    healed[pid] = "terminated"
            except (ResourceNotFoundError, ProjectStateError):
                continue

        return await self.update(
            run_id=run_id,
            tenant_key=tenant_key,
            status="cancelled",
            project_statuses={**member_statuses, **healed} if healed else None,
        )

    async def deactivate_chain(
        self,
        *,
        run_id: str,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        from giljo_mcp.services.project_service import ProjectService

        run = await self.get(run_id=run_id, tenant_key=tenant_key)
        member_ids: list[str] = run.get("resolved_order") or run.get("project_ids") or []

        proj_svc = ProjectService(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            test_session=self._session,
        )
        for pid in member_ids:
            try:
                await proj_svc.lifecycle.reset_to_prestage(pid, tenant_key=tenant_key)
            except ResourceNotFoundError:
                continue

        return await self.update(
            run_id=run_id,
            tenant_key=tenant_key,
            status="cancelled",
            clear_conductor=True,
        )
