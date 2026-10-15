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
from giljo_mcp.repositories.agent_job_repository import AgentJobRepository
from giljo_mcp.services.agent_job_manager import AgentJobManager
from giljo_mcp.services.closeout_ws_broadcast import broadcast_agent_status_changed


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

        return await self._cancel_run_and_retire_conductor(run, {**member_statuses, **healed} if healed else None)

    async def _cancel_run_and_retire_conductor(
        self, run: dict[str, Any], project_statuses: dict[str, str] | None
    ) -> dict[str, Any]:
        from giljo_mcp.services.sequence_run_service import broadcast_deferred_sequence_updates

        tenant_key = run["tenant_key"]
        conductor_events = []
        async with self._get_session(tenant_key) as session:
            conductor = None
            if run.get("conductor_agent_id"):
                conductor = await AgentJobRepository(None).get_execution_by_agent_id(
                    session, tenant_key, run["conductor_agent_id"]
                )
            if conductor is not None:
                conductor_events = await AgentJobManager(
                    self.db_manager, self.tenant_manager, test_session=session
                ).decommission_job(conductor.job_id, tenant_key)
            stopped = await type(self)(
                db_manager=self.db_manager,
                tenant_manager=self.tenant_manager,
                session=session,
                websocket_manager=self._websocket_manager,
            ).update(
                run_id=run["id"],
                tenant_key=tenant_key,
                status="cancelled",
                project_statuses=project_statuses,
                defer_broadcast=True,
            )
        await broadcast_deferred_sequence_updates(session)
        for event in conductor_events:
            await broadcast_agent_status_changed(
                self._websocket_manager, tenant_key=tenant_key, project_id=None, event=event
            )
        return stopped

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
