# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.projects import Project


class OrchestratorFixtureMixin:

    async def _ensure_orchestrator_fixture(
        self,
        session: AsyncSession,
        project: Project,
        websocket_manager: Any | None = None,
    ) -> dict[str, str] | None:
        tenant_key = self.tenant_manager.get_current_tenant()

        existing = await self._repo.find_existing_orchestrator(session, tenant_key, str(project.id))

        if existing:
            self._logger.info(
                f"[ORCHESTRATOR FIXTURE] Orchestrator already exists for project {project.id}, "
                f"job_id={existing.job_id}, status={existing.status}"
            )
            return None

        fixture_ids = await self._repo.create_orchestrator_fixture(session, tenant_key, project)

        await session.commit()

        job_id = fixture_ids["job_id"]
        agent_id = fixture_ids["agent_id"]
        execution_id = fixture_ids["execution_id"]

        self._logger.info(
            f"[ORCHESTRATOR FIXTURE] Created orchestrator fixture for project {project.id}: "
            f"job_id={job_id}, agent_id={agent_id}"
        )

        if websocket_manager:
            await websocket_manager.broadcast_to_tenant(
                tenant_key=tenant_key,
                event_type="agent:created",
                data={
                    "project_id": project.id,
                    "product_id": project.product_id,
                    "execution_id": execution_id,
                    "agent_id": agent_id,
                    "job_id": job_id,
                    "agent_display_name": "orchestrator",
                    "agent_name": "orchestrator",
                    "status": "waiting",
                    "fixture": True,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            self._logger.info(f"[ORCHESTRATOR FIXTURE] Broadcast agent:created for {job_id}")

        return {
            "job_id": job_id,
            "agent_id": agent_id,
        }

    async def _maybe_reset_never_run_orchestrator(
        self,
        session: AsyncSession,
        tenant_key: str,
        project: Project,
    ) -> list[dict]:
        orchestrators = await self._repo.find_active_orchestrator_executions(session, tenant_key, str(project.id))
        if not orchestrators:
            return []

        never_ran = all(o.status in ("waiting", "staged") and o.working_started_at is None for o in orchestrators)
        if not never_ran:
            return []

        if await self._repo.count_non_orchestrator_executions(session, tenant_key, str(project.id)) > 0:
            return []

        deleted = await self._repo.delete_never_run_orchestrator_fixtures(
            session, tenant_key, str(project.id), ["waiting", "staged"]
        )
        project.staging_status = None
        project.mission = ""
        project.implementation_launched_at = None

        self._logger.info(
            "[BE-6123] Deleted never-run orchestrator fixture for project %s (%d row(s) removed)",
            project.id,
            len(deleted),
        )
        return deleted

    async def _broadcast_agents_removed(
        self,
        ws_mgr: Any | None,
        tenant_key: str,
        project_id: str,
        removed: list[dict],
        product_id: str | None = None,
    ) -> None:
        if not ws_mgr or not removed:
            return
        for row in removed:
            await ws_mgr.broadcast_to_tenant(
                tenant_key=tenant_key,
                event_type="agent:removed",
                data={
                    "project_id": project_id,
                    "product_id": product_id,
                    "agent_id": row["agent_id"],
                    "execution_id": row["execution_id"],
                    "job_id": row["job_id"],
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
