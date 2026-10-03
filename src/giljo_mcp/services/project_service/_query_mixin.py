# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any

from sqlalchemy import select

from giljo_mcp.domain.project_status import is_review_pending
from giljo_mcp.exceptions import (
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.schemas.service_responses import (
    ProjectDetail,
    ProjectListItem,
)


class QueryMixin:

    async def get_project_type_by_label(self, label: str, tenant_key: str) -> TaxonomyType | None:
        from giljo_mcp.services.taxonomy_ops import RESERVED_TYPE_ABBRS

        if (label or "").strip().upper() in RESERVED_TYPE_ABBRS:
            return None

        from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded

        async with self._get_session(tenant_key) as session:
            await ensure_default_types_seeded(session, tenant_key)
            match = await self._repo.get_project_type_by_label(session, tenant_key, label)
            if not match:
                match = await self._repo.get_project_type_by_abbreviation(session, tenant_key, label)

            if match and match.abbreviation in RESERVED_TYPE_ABBRS:
                return None
            return match

    async def get_project(self, project_id: str, tenant_key: str) -> ProjectDetail:
        if not tenant_key:
            raise ValidationError("tenant_key is required for security (Handover 0424 Phase 0)")

        try:
            async with self._get_session(tenant_key) as session:
                project = await self._repo.get_by_id_with_type(session, tenant_key, project_id)

                if not project:
                    raise ResourceNotFoundError(
                        message="Project not found or access denied",
                        context={"project_id": project_id, "tenant_key": tenant_key},
                    )

                agent_pairs = await self._repo.get_agent_pairs_for_project(session, tenant_key, project_id)

                agent_dicts = [
                    {
                        "id": job.job_id,
                        "job_id": job.job_id,
                        "agent_display_name": job.job_type,
                        "agent_name": execution.agent_name,
                        "status": execution.status,
                        "messages_sent_count": execution.messages_sent_count,
                        "messages_waiting_count": execution.messages_waiting_count,
                        "messages_read_count": execution.messages_read_count,
                        "thin_client": True,
                    }
                    for job, execution in agent_pairs
                ]

                self._logger.info(f"Retrieved project {project.name} with {len(agent_dicts)} agents")

                return ProjectDetail(
                    id=str(project.id),
                    alias=project.alias,
                    name=project.name,
                    mission=project.mission,
                    description=project.description,
                    status=project.status,
                    staging_status=project.staging_status,
                    implementation_launched_at=(
                        project.implementation_launched_at.isoformat() if project.implementation_launched_at else None
                    ),
                    reviewed_at=project.reviewed_at.isoformat() if project.reviewed_at else None,
                    review_pending=is_review_pending(project.status, project.reviewed_at),
                    product_id=project.product_id,
                    tenant_key=project.tenant_key,
                    execution_mode=project.execution_mode,
                    auto_checkin_enabled=project.auto_checkin_enabled,
                    auto_checkin_interval=project.auto_checkin_interval,
                    cancellation_reason=project.cancellation_reason,
                    early_termination=project.early_termination,
                    created_at=project.created_at.isoformat() if project.created_at else None,
                    updated_at=project.updated_at.isoformat() if project.updated_at else None,
                    completed_at=project.completed_at.isoformat() if project.completed_at else None,
                    agents=agent_dicts,
                    agent_count=len(agent_dicts),
                    message_count=0,
                    project_type_id=project.project_type_id,
                    project_type=project.project_type,
                    series_number=project.series_number,
                    subseries=project.subseries,
                    taxonomy_alias=project.taxonomy_alias,
                    successor_project_id=project.successor_project_id,
                )

        except (ValueError, ResourceNotFoundError):
            raise
        except Exception as e:
            self._logger.exception("Failed to get project")
            raise BaseGiljoError(
                message=f"Failed to get project: {e!s}", context={"project_id": project_id, "tenant_key": tenant_key}
            ) from e

    async def list_projects(
        self,
        status: str | list[str] | None = None,
        tenant_key: str | None = None,
        include_cancelled: bool = False,
        product_id: str | None = None,
        hidden: bool | None = None,
        search: str | None = None,
        sort_key: str | None = None,
        sort_dir: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        after_key: tuple[Any, str] | None = None,
    ) -> list[ProjectListItem]:
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()

            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"operation": "list_projects"})

            async with self.db_manager.get_tenant_session_async(tenant_key) as session:
                projects = await self._repo.list_projects(
                    session,
                    tenant_key,
                    status,
                    include_cancelled,
                    product_id,
                    hidden=hidden,
                    search=search,
                    sort_key=sort_key,
                    sort_dir=sort_dir,
                    limit=limit,
                    offset=offset,
                    after_key=after_key,
                )

                return [
                    ProjectListItem(
                        id=str(project.id),
                        name=project.name,
                        mission=project.mission,
                        description=project.description,
                        status=project.status,
                        staging_status=project.staging_status,
                        implementation_launched_at=(
                            project.implementation_launched_at.isoformat()
                            if project.implementation_launched_at
                            else None
                        ),
                        tenant_key=project.tenant_key,
                        product_id=project.product_id,
                        created_at=project.created_at.isoformat(),
                        updated_at=(
                            project.updated_at.isoformat() if project.updated_at else project.created_at.isoformat()
                        ),
                        completed_at=(project.completed_at.isoformat() if project.completed_at else None),
                        execution_mode=project.execution_mode,
                        project_type_id=project.project_type_id,
                        project_type=project.project_type,
                        series_number=project.series_number,
                        subseries=project.subseries,
                        taxonomy_alias=project.taxonomy_alias,
                        hidden=project.hidden is True,
                    )
                    for project in projects
                ]

        except ValidationError:
            raise
        except Exception as e:
            self._logger.exception("Failed to list projects")
            raise BaseGiljoError(message=f"Failed to list projects: {e!s}", context={"tenant_key": tenant_key}) from e

    async def board_counts(
        self,
        tenant_key: str | None = None,
        product_id: str | None = None,
    ) -> list[tuple]:
        if not tenant_key:
            tenant_key = self.tenant_manager.get_current_tenant()
        if not tenant_key:
            raise ValidationError(message="No tenant context available", context={"operation": "board_counts"})

        async with self.db_manager.get_tenant_session_async(tenant_key) as session:
            return await self._repo.board_counts(session, tenant_key, product_id=product_id)

    async def count_projects(
        self,
        status: str | list[str] | None = None,
        tenant_key: str | None = None,
        include_cancelled: bool = False,
        product_id: str | None = None,
        hidden: bool | None = None,
        search: str | None = None,
    ) -> int:
        try:
            if not tenant_key:
                tenant_key = self.tenant_manager.get_current_tenant()

            if not tenant_key:
                raise ValidationError(message="No tenant context available", context={"operation": "count_projects"})

            async with self.db_manager.get_tenant_session_async(tenant_key) as session:
                return await self._repo.count_projects(
                    session,
                    tenant_key,
                    status,
                    include_cancelled,
                    product_id,
                    hidden=hidden,
                    search=search,
                )

        except ValidationError:
            raise
        except Exception as e:
            self._logger.exception("Failed to count projects")
            raise BaseGiljoError(message=f"Failed to count projects: {e!s}", context={"tenant_key": tenant_key}) from e

    async def get_project_type_by_id(self, type_id: str, tenant_key: str) -> TaxonomyType | None:
        async with self._get_session(tenant_key) as session:
            result = await session.execute(
                select(TaxonomyType).where(
                    TaxonomyType.tenant_key == tenant_key,
                    TaxonomyType.id == type_id,
                )
            )
            return result.scalar_one_or_none()
