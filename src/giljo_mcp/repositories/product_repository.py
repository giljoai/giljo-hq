# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy import delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models import Product, Project, Task
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.config import Configuration
from giljo_mcp.models.products import (
    ProductArchitecture,
    ProductTechStack,
    ProductTestConfig,
)
from giljo_mcp.models.tasks import Message
from giljo_mcp.models.user_approval import UserApproval


logger = logging.getLogger(__name__)


class ProductRepository:

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")


    async def get_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str,
        *,
        include_deleted: bool = False,
        eager_load: bool = False,
    ) -> Product | None:
        conditions = [Product.id == product_id, Product.tenant_key == tenant_key]
        if not include_deleted:
            conditions.append(Product.deleted_at.is_(None))

        stmt = select(Product).where(and_(*conditions))

        if eager_load:
            stmt = stmt.options(
                selectinload(Product.vision_documents),
                selectinload(Product.tech_stack),
                selectinload(Product.architecture),
                selectinload(Product.test_config),
            )

        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(
        self,
        session: AsyncSession,
        tenant_key: str,
        name: str,
    ) -> Product | None:
        stmt = select(Product).where(
            and_(
                Product.tenant_key == tenant_key,
                Product.name == name,
                Product.deleted_at.is_(None),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_default_product(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        eager_load: bool = True,
    ) -> Product | None:

        def _apply_eager(stmt):
            if eager_load:
                return stmt.options(
                    selectinload(Product.vision_documents),
                    selectinload(Product.tech_stack),
                    selectinload(Product.architecture),
                    selectinload(Product.test_config),
                )
            return stmt

        stmt = _apply_eager(
            select(Product).where(
                and_(
                    Product.tenant_key == tenant_key,
                    Product.is_default,
                    Product.deleted_at.is_(None),
                )
            )
        )
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()
        if product is not None:
            return product

        count_stmt = (
            select(func.count())
            .select_from(Product)
            .where(and_(Product.tenant_key == tenant_key, Product.is_active, Product.deleted_at.is_(None)))
        )
        count = (await session.execute(count_stmt)).scalar_one()
        if count != 1:
            return None

        sole_stmt = _apply_eager(
            select(Product).where(
                and_(Product.tenant_key == tenant_key, Product.is_active, Product.deleted_at.is_(None))
            )
        )
        result = await session.execute(sole_stmt)
        return result.scalar_one_or_none()

    async def count_active_products(self, session: AsyncSession, tenant_key: str) -> int:
        count_stmt = (
            select(func.count())
            .select_from(Product)
            .where(and_(Product.tenant_key == tenant_key, Product.is_active, Product.deleted_at.is_(None)))
        )
        return (await session.execute(count_stmt)).scalar_one()

    async def find_other_default_products(
        self,
        session: AsyncSession,
        tenant_key: str,
        exclude_product_id: str,
    ) -> list[Product]:
        stmt = select(Product).where(
            and_(
                Product.tenant_key == tenant_key,
                Product.is_default,
                Product.id != exclude_product_id,
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_products(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        include_inactive: bool = False,
        lean: bool = False,
    ) -> list[Product]:
        conditions = [Product.tenant_key == tenant_key, Product.deleted_at.is_(None)]

        if not include_inactive:
            conditions.append(Product.is_active)

        stmt = select(Product).where(and_(*conditions))
        if not lean:
            stmt = stmt.options(
                selectinload(Product.vision_documents),
                selectinload(Product.tech_stack),
                selectinload(Product.architecture),
                selectinload(Product.test_config),
            )
        stmt = stmt.order_by(Product.is_active.desc(), Product.created_at.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_deleted(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> list[Product]:
        stmt = (
            select(Product)
            .where(
                and_(
                    Product.tenant_key == tenant_key,
                    Product.deleted_at.isnot(None),
                )
            )
            .order_by(Product.deleted_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_deleted_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str,
    ) -> Product | None:
        stmt = select(Product).where(
            and_(
                Product.id == product_id,
                Product.tenant_key == tenant_key,
                Product.deleted_at.isnot(None),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_expired_deleted(
        self,
        session: AsyncSession,
        days_before_purge: int = 10,
    ) -> list[Product]:
        cutoff_date = datetime.now(UTC) - timedelta(days=days_before_purge)
        stmt = select(Product).where(
            Product.deleted_at.isnot(None),
            Product.deleted_at < cutoff_date,
        )
        with tenant_isolation_bypass(
            session,
            reason="startup purge scans soft-deleted products across tenants",
            models=(Product,),
        ):
            result = await session.execute(stmt)
        return list(result.scalars().all())


    async def add(self, session: AsyncSession, product: Product) -> None:
        session.add(product)

    async def delete_blocking_dependants(
        self, session: AsyncSession, tenant_key: str, product_id: str
    ) -> dict[str, int]:
        project_ids = (
            select(Project.id)
            .where(and_(Project.product_id == product_id, Project.tenant_key == tenant_key))
            .scalar_subquery()
        )
        job_ids = (
            select(AgentJob.job_id)
            .where(and_(AgentJob.project_id.in_(project_ids), AgentJob.tenant_key == tenant_key))
            .scalar_subquery()
        )

        counts: dict[str, int] = {}
        for label, stmt in (
            (
                "user_approvals",
                sql_delete(UserApproval).where(
                    and_(UserApproval.project_id.in_(project_ids), UserApproval.tenant_key == tenant_key)
                ),
            ),
            (
                "agent_executions",
                sql_delete(AgentExecution).where(
                    and_(AgentExecution.job_id.in_(job_ids), AgentExecution.tenant_key == tenant_key)
                ),
            ),
            (
                "agent_jobs",
                sql_delete(AgentJob).where(
                    and_(AgentJob.project_id.in_(project_ids), AgentJob.tenant_key == tenant_key)
                ),
            ),
            (
                "configurations",
                sql_delete(Configuration).where(
                    and_(Configuration.project_id.in_(project_ids), Configuration.tenant_key == tenant_key)
                ),
            ),
            (
                "messages",
                sql_delete(Message).where(and_(Message.project_id.in_(project_ids), Message.tenant_key == tenant_key)),
            ),
            (
                "tasks",
                sql_delete(Task).where(
                    and_(
                        or_(Task.project_id.in_(project_ids), Task.converted_to_project_id.in_(project_ids)),
                        Task.tenant_key == tenant_key,
                    )
                ),
            ),
        ):
            result = await session.execute(stmt)
            counts[label] = result.rowcount or 0

        return counts

    async def delete_hard(self, session: AsyncSession, product: Product) -> None:
        await session.delete(product)

    async def flush(self, session: AsyncSession) -> None:
        await session.flush()

    async def refresh(
        self,
        session: AsyncSession,
        product: Product,
        *,
        include_relations: bool = True,
    ) -> None:
        if include_relations:
            await session.refresh(
                product,
                attribute_names=["tech_stack", "architecture", "test_config", "vision_documents"],
            )
        else:
            await session.refresh(product)


    async def create_config_relations(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
        config_data: dict,
    ) -> None:
        tech_stack = config_data.get("tech_stack")
        if tech_stack and isinstance(tech_stack, dict):
            ts = ProductTechStack(
                product_id=product_id,
                tenant_key=tenant_key,
                programming_languages=tech_stack.get("programming_languages", ""),
                frontend_frameworks=tech_stack.get("frontend_frameworks", ""),
                backend_frameworks=tech_stack.get("backend_frameworks", ""),
                databases_storage=tech_stack.get("databases_storage", ""),
                infrastructure=tech_stack.get("infrastructure", ""),
                dev_tools=tech_stack.get("dev_tools", ""),
            )
            session.add(ts)

        architecture = config_data.get("architecture")
        if architecture and isinstance(architecture, dict):
            arch = ProductArchitecture(
                product_id=product_id,
                tenant_key=tenant_key,
                primary_pattern=architecture.get("primary_pattern", ""),
                design_patterns=architecture.get("design_patterns", ""),
                api_style=architecture.get("api_style", ""),
                architecture_notes=architecture.get("architecture_notes", ""),
                coding_conventions=architecture.get("coding_conventions", ""),
            )
            session.add(arch)

        test_config = config_data.get("test_config")
        if test_config and isinstance(test_config, dict):
            tc = ProductTestConfig(
                product_id=product_id,
                tenant_key=tenant_key,
                quality_standards=test_config.get("quality_standards", ""),
                test_strategy=test_config.get("test_strategy", ""),
                coverage_target=test_config.get("coverage_target", 80),
                testing_frameworks=test_config.get("testing_frameworks", ""),
            )
            session.add(tc)

    async def update_config_relations(
        self,
        session: AsyncSession,
        product: Product,
        tenant_key: str,
        config_data: dict,
    ) -> None:
        tech_stack = config_data.get("tech_stack")
        if tech_stack and isinstance(tech_stack, dict):
            ts = product.tech_stack
            if ts is None:
                ts = ProductTechStack(product_id=product.id, tenant_key=tenant_key)
                session.add(ts)
                product.tech_stack = ts
            for field in (
                "programming_languages",
                "frontend_frameworks",
                "backend_frameworks",
                "databases_storage",
                "infrastructure",
                "dev_tools",
            ):
                if field in tech_stack:
                    setattr(ts, field, tech_stack[field])

        architecture = config_data.get("architecture")
        if architecture and isinstance(architecture, dict):
            arch = product.architecture
            if arch is None:
                arch = ProductArchitecture(product_id=product.id, tenant_key=tenant_key)
                session.add(arch)
                product.architecture = arch
            for field in (
                "primary_pattern",
                "design_patterns",
                "api_style",
                "architecture_notes",
                "coding_conventions",
            ):
                if field in architecture:
                    setattr(arch, field, architecture[field])

        test_config = config_data.get("test_config")
        if test_config and isinstance(test_config, dict):
            tc = product.test_config
            if tc is None:
                tc = ProductTestConfig(product_id=product.id, tenant_key=tenant_key)
                session.add(tc)
                product.test_config = tc
            for field in ("quality_standards", "test_strategy", "coverage_target", "testing_frameworks"):
                if field in test_config:
                    setattr(tc, field, test_config[field])

