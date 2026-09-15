# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.products import Product
from giljo_mcp.product_crew import seed_product_crew


async def make_product(session: AsyncSession, tenant_key: str, name: str | None = None) -> Product:
    product = Product(
        id=str(uuid4()),
        name=name or f"Crew fixture {uuid4().hex[:8]}",
        description="test fixture",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    session.add(product)
    await session.commit()
    return product


async def seed_crew(
    session: AsyncSession, tenant_key: str, product: Product | None = None
) -> tuple[Product, list[str]]:
    if product is None:
        product = await make_product(session, tenant_key)
    names = await seed_product_crew(session, tenant_key, product.id)
    await session.commit()
    return product, names


async def adopt_all_templates(session: AsyncSession, tenant_key: str, product_id: str) -> int:
    from sqlalchemy import select

    from giljo_mcp.database import tenant_session_context
    from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
    from giljo_mcp.models.templates import AgentTemplate

    with tenant_session_context(session, tenant_key):
        rows = list(
            (
                await session.execute(
                    select(AgentTemplate).where(
                        AgentTemplate.tenant_key == tenant_key,
                        AgentTemplate.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        existing = {
            r[0]
            for r in (
                await session.execute(
                    select(ProductAgentAssignment.template_id).where(
                        ProductAgentAssignment.product_id == product_id,
                        ProductAgentAssignment.tenant_key == tenant_key,
                    )
                )
            ).all()
        }
        for template in rows:
            template.product_id = product_id
            if template.id not in existing:
                session.add(
                    ProductAgentAssignment(
                        id=str(uuid4()),
                        product_id=product_id,
                        template_id=template.id,
                        tenant_key=tenant_key,
                        is_active=True,
                    )
                )
    await session.commit()
    return len(rows)
