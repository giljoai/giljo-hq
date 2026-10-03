# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Select, and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.projects import Project
from giljo_mcp.models.user_approval import UserApproval
from giljo_mcp.schemas.jsonb_validators import validate_agent_job_metadata


logger = logging.getLogger(__name__)


def _live_orchestrators(tenant_key: str, project_id: str) -> Select:
    return (
        select(AgentExecution)
        .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
        .where(
            AgentJob.project_id == project_id,
            AgentExecution.agent_display_name == "orchestrator",
            AgentExecution.tenant_key == tenant_key,
            ~AgentExecution.status.in_(["decommissioned"]),
        )
    )


class ProjectLifecycleRepository:

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")


    async def get_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> Project | None:
        result = await session.execute(
            select(Project).where(
                and_(
                    Project.id == project_id,
                    Project.tenant_key == tenant_key,
                )
            )
        )
        return result.scalar_one_or_none()

    async def find_existing_orchestrator(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> AgentExecution | None:
        result = await session.execute(_live_orchestrators(tenant_key, project_id))
        return result.scalar_one_or_none()

    async def find_decommissioned_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list[AgentExecution]:
        result = await session.execute(
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentJob.tenant_key == tenant_key,
                    AgentExecution.status == "decommissioned",
                )
            )
        )
        return list(result.scalars().all())

    async def find_active_orchestrator_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> list[AgentExecution]:
        result = await session.execute(_live_orchestrators(tenant_key, project_id))
        return list(result.scalars().all())

    async def count_non_orchestrator_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == project_id,
                AgentJob.tenant_key == tenant_key,
                AgentExecution.agent_display_name != "orchestrator",
                AgentExecution.status.not_in(["decommissioned"]),
            )
        )
        return result.scalar() or 0

    async def delete_never_run_orchestrator_fixtures(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        statuses: list[str],
    ) -> list[dict]:
        candidates = (
            (
                await session.execute(
                    select(AgentExecution)
                    .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
                    .where(
                        AgentJob.project_id == project_id,
                        AgentJob.tenant_key == tenant_key,
                        AgentExecution.tenant_key == tenant_key,
                        AgentExecution.agent_display_name == "orchestrator",
                        AgentExecution.working_started_at.is_(None),
                        AgentExecution.status.in_(statuses),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not candidates:
            return []

        job_to_execs: dict[str, list[AgentExecution]] = {}
        for job_id in {c.job_id for c in candidates}:
            execs = (
                (
                    await session.execute(
                        select(AgentExecution).where(
                            AgentExecution.job_id == job_id,
                            AgentExecution.tenant_key == tenant_key,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if execs and all(
                e.agent_display_name == "orchestrator" and e.working_started_at is None and e.status in statuses
                for e in execs
            ):
                job_to_execs[job_id] = list(execs)
        if not job_to_execs:
            return []

        all_exec_ids = [e.id for execs in job_to_execs.values() for e in execs]
        referenced = (
            await session.execute(
                select(UserApproval.agent_execution_id, UserApproval.job_id).where(
                    UserApproval.tenant_key == tenant_key,
                    or_(
                        UserApproval.agent_execution_id.in_(all_exec_ids),
                        UserApproval.job_id.in_(list(job_to_execs.keys())),
                    ),
                )
            )
        ).all()
        blocked_exec_ids = {row[0] for row in referenced}
        blocked_job_ids = {row[1] for row in referenced}
        for job_id in list(job_to_execs.keys()):
            execs = job_to_execs[job_id]
            if job_id in blocked_job_ids or any(e.id in blocked_exec_ids for e in execs):
                self._logger.warning(
                    "[BE-6123] Skipping never-run orchestrator job %s for project %s: referenced by a user_approval",
                    job_id,
                    project_id,
                )
                del job_to_execs[job_id]
        if not job_to_execs:
            return []

        deleted: list[dict] = []
        exec_ids: list[str] = []
        for job_id, execs in job_to_execs.items():
            for e in execs:
                deleted.append({"execution_id": str(e.id), "agent_id": e.agent_id, "job_id": job_id})
                exec_ids.append(e.id)

        await session.execute(
            delete(AgentExecution).where(
                AgentExecution.id.in_(exec_ids),
                AgentExecution.tenant_key == tenant_key,
            )
        )
        await session.execute(
            delete(AgentJob).where(
                AgentJob.job_id.in_(list(job_to_execs.keys())),
                AgentJob.tenant_key == tenant_key,
            )
        )
        return deleted

    async def delete_all_agent_state_for_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> dict[str, int]:
        job_ids = (
            (
                await session.execute(
                    select(AgentJob.job_id).where(
                        AgentJob.project_id == project_id,
                        AgentJob.tenant_key == tenant_key,
                    )
                )
            )
            .scalars()
            .all()
        )
        if not job_ids:
            return {"jobs": 0, "executions": 0, "approvals": 0}

        exec_ids = (
            (
                await session.execute(
                    select(AgentExecution.id).where(
                        AgentExecution.job_id.in_(job_ids),
                        AgentExecution.tenant_key == tenant_key,
                    )
                )
            )
            .scalars()
            .all()
        )

        approval_conds = [UserApproval.job_id.in_(job_ids)]
        if exec_ids:
            approval_conds.append(UserApproval.agent_execution_id.in_(exec_ids))
        appr = await session.execute(
            delete(UserApproval).where(
                UserApproval.tenant_key == tenant_key,
                or_(*approval_conds),
            )
        )
        await session.execute(
            delete(AgentExecution).where(
                AgentExecution.job_id.in_(job_ids),
                AgentExecution.tenant_key == tenant_key,
            )
        )
        await session.execute(
            delete(AgentJob).where(
                AgentJob.job_id.in_(job_ids),
                AgentJob.tenant_key == tenant_key,
            )
        )
        return {"jobs": len(job_ids), "executions": len(exec_ids), "approvals": appr.rowcount or 0}


    async def flush(self, session: AsyncSession) -> None:
        await session.flush()

    async def refresh(self, session: AsyncSession, entity: Project | AgentJob | AgentExecution) -> None:
        await session.refresh(entity)

    async def cancel_project(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        reason: str | None = None,
    ) -> int:
        update_values: dict = {
            "status": ProjectStatus.CANCELLED,
            "completed_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        if reason:
            update_values["cancellation_reason"] = reason

        result = await session.execute(
            update(Project)
            .where(and_(Project.id == project_id, Project.tenant_key == tenant_key))
            .values(**update_values)
        )
        return result.rowcount

    async def create_orchestrator_fixture(
        self,
        session: AsyncSession,
        tenant_key: str,
        project: Project,
    ) -> dict[str, str]:
        job_id = str(uuid4())
        agent_id = str(uuid4())

        agent_job = AgentJob(
            job_id=job_id,
            tenant_key=tenant_key,
            project_id=project.id,
            mission=f"Orchestrator for project: {project.name}",
            job_type="orchestrator",
            status="active",
            job_metadata=validate_agent_job_metadata(
                {
                    "created_via": "project_activation_fixture",
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ),
        )
        session.add(agent_job)

        agent_execution = AgentExecution(
            agent_id=agent_id,
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="waiting",
            progress=0,
            health_status="unknown",
            project_phase="staging",
        )
        session.add(agent_execution)

        await session.flush()
        await session.refresh(agent_job)
        await session.refresh(agent_execution)

        return {
            "job_id": job_id,
            "agent_id": agent_id,
            "execution_id": str(agent_execution.id),
        }


    async def get_active_agent_executions(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        exclude_statuses: list[str] | None = None,
    ) -> list[AgentExecution]:
        if exclude_statuses is None:
            exclude_statuses = ["complete", "decommissioned"]
        result = await session.execute(
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentJob.tenant_key == tenant_key,
                    AgentExecution.status.notin_(exclude_statuses),
                )
            )
        )
        return list(result.scalars().all())

    async def get_executions_by_status(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
        statuses: list[str],
    ) -> list[AgentExecution]:
        result = await session.execute(
            select(AgentExecution)
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentExecution.tenant_key == tenant_key,
                    AgentExecution.status.in_(statuses),
                )
            )
        )
        return list(result.scalars().all())

    async def get_agent_status_counts(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> dict:
        from sqlalchemy import func

        job_counts_result = await session.execute(
            select(AgentExecution.status, func.count(AgentExecution.agent_id).label("count"))
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentJob.tenant_key == tenant_key,
                )
            )
            .group_by(AgentExecution.status)
        )
        return dict(job_counts_result.all())

    async def add_entity(self, session: AsyncSession, entity) -> None:
        session.add(entity)

    async def find_non_decommissioned_orchestrator(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> AgentExecution | None:
        stmt = _live_orchestrators(tenant_key, project_id).order_by(AgentExecution.started_at.desc())
        return (await session.execute(stmt)).scalars().first()

    async def get_user(
        self,
        session: AsyncSession,
        tenant_key: str,
        user_id: str,
    ):
        from giljo_mcp.models.auth import User

        result = await session.execute(select(User).where(and_(User.id == user_id, User.tenant_key == tenant_key)))
        return result.scalar_one_or_none()

    async def get_user_field_priorities(
        self,
        session: AsyncSession,
        tenant_key: str,
        user_id: str,
    ) -> list:
        from giljo_mcp.models.auth import UserFieldPriority

        result = await session.execute(
            select(UserFieldPriority).where(
                and_(
                    UserFieldPriority.user_id == user_id,
                    UserFieldPriority.tenant_key == tenant_key,
                )
            )
        )
        return list(result.scalars().all())

    async def stand_down_project_agents(
        self,
        session: AsyncSession,
        tenant_key: str,
        project_id: str,
    ) -> dict[str, int]:
        now = datetime.now(UTC)

        job_ids_result = await session.execute(
            select(AgentJob.job_id).where(
                and_(
                    AgentJob.project_id == project_id,
                    AgentJob.tenant_key == tenant_key,
                )
            )
        )
        job_ids = [row[0] for row in job_ids_result.all()]
        if not job_ids:
            return {"jobs": 0, "executions": 0}

        executions = await session.execute(
            update(AgentExecution)
            .where(
                and_(
                    AgentExecution.tenant_key == tenant_key,
                    AgentExecution.job_id.in_(job_ids),
                    AgentExecution.status.notin_(["complete", "decommissioned"]),
                )
            )
            .values(status="decommissioned", completed_at=now)
        )
        jobs = await session.execute(
            update(AgentJob)
            .where(
                and_(
                    AgentJob.job_id.in_(job_ids),
                    AgentJob.tenant_key == tenant_key,
                    AgentJob.status.notin_(["completed", "cancelled"]),
                )
            )
            .values(status="cancelled", completed_at=now)
        )
        return {"jobs": jobs.rowcount or 0, "executions": executions.rowcount or 0}
