# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging

from sqlalchemy import and_, func, select, update
from sqlalchemy import delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentJob
from giljo_mcp.models.templates import AgentTemplate, TemplateArchive


logger = logging.getLogger(__name__)


class TemplateRepository:

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")


    async def add_template(self, session: AsyncSession, template: AgentTemplate) -> None:
        session.add(template)

    async def add_and_flush_template(self, session: AsyncSession, template: AgentTemplate) -> AgentTemplate:
        session.add(template)
        await session.flush()
        await session.refresh(template)
        return template


    async def nullify_job_template_refs(self, session: AsyncSession, template_id: str) -> None:
        await session.execute(update(AgentJob).where(AgentJob.template_id == template_id).values(template_id=None))

    async def delete_archives(self, session: AsyncSession, template_id: str) -> None:
        await session.execute(
            sql_delete(TemplateArchive.__table__).where(TemplateArchive.__table__.c.template_id == template_id)
        )

    async def delete_template(self, session: AsyncSession, template: AgentTemplate) -> None:
        await session.delete(template)


    async def add_archive(self, session: AsyncSession, archive: TemplateArchive) -> None:
        session.add(archive)


    async def get_by_id(
        self,
        session: AsyncSession,
        template_id: str,
        tenant_key: str,
    ) -> AgentTemplate | None:
        stmt = select(AgentTemplate).where(
            and_(
                AgentTemplate.id == template_id,
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.deleted_at.is_(None),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(
        self,
        session: AsyncSession,
        name: str,
        tenant_key: str,
    ) -> AgentTemplate | None:
        stmt = select(AgentTemplate).where(
            and_(
                AgentTemplate.name == name,
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.deleted_at.is_(None),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_with_filters(
        self,
        session: AsyncSession,
        tenant_key: str,
        role: str | None = None,
        is_active: bool | None = None,
        product_id: str | None = None,
    ) -> list[AgentTemplate]:
        query = select(AgentTemplate).where(
            AgentTemplate.tenant_key == tenant_key,
            AgentTemplate.deleted_at.is_(None),
        )
        if role:
            query = query.where(AgentTemplate.role == role)
        if is_active is not None:
            query = query.where(AgentTemplate.is_active == is_active)
        if product_id:
            query = query.where(AgentTemplate.product_id == product_id)
        result = await session.execute(query)
        return list(result.scalars().all())

    async def check_name_exists(
        self,
        session: AsyncSession,
        tenant_key: str,
        name: str,
    ) -> bool:
        stmt = select(func.count(AgentTemplate.id)).where(
            and_(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.name == name,
                AgentTemplate.deleted_at.is_(None),
            )
        )
        result = await session.execute(stmt)
        return result.scalar() > 0

    async def get_defaults_by_role(
        self,
        session: AsyncSession,
        tenant_key: str,
        role: str,
    ) -> list[AgentTemplate]:
        stmt = select(AgentTemplate).where(
            and_(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.role == role,
                AgentTemplate.is_default,
                AgentTemplate.deleted_at.is_(None),
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_template_role(
        self,
        session: AsyncSession,
        template_id: str,
    ) -> str | None:
        stmt = select(AgentTemplate.role).where(
            AgentTemplate.id == template_id,
            AgentTemplate.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


    async def get_deleted_template_by_id(
        self,
        session: AsyncSession,
        template_id: str,
        tenant_key: str,
    ) -> AgentTemplate | None:
        stmt = select(AgentTemplate).where(
            and_(
                AgentTemplate.id == template_id,
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.deleted_at.isnot(None),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_deleted(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> list[AgentTemplate]:
        stmt = (
            select(AgentTemplate)
            .where(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.deleted_at.isnot(None),
            )
            .order_by(AgentTemplate.deleted_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def flush(self, session: AsyncSession) -> None:
        await session.flush()

    async def flush_and_refresh(self, session: AsyncSession, entity: AgentTemplate) -> None:
        await session.flush()
        await session.refresh(entity)

    async def get_template_history(
        self,
        session: AsyncSession,
        template_id: str,
        tenant_key: str,
    ) -> list[TemplateArchive]:
        stmt = (
            select(TemplateArchive)
            .where(
                TemplateArchive.template_id == template_id,
                TemplateArchive.tenant_key == tenant_key,
            )
            .order_by(TemplateArchive.archived_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_archive_by_id(
        self,
        session: AsyncSession,
        archive_id: str,
        template_id: str,
        tenant_key: str,
    ) -> TemplateArchive | None:
        stmt = select(TemplateArchive).where(
            TemplateArchive.id == archive_id,
            TemplateArchive.template_id == template_id,
            TemplateArchive.tenant_key == tenant_key,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
