# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.repositories.product_agent_assignment_repository import (
    ProductAgentAssignmentRepository,
)


logger = logging.getLogger(__name__)


async def template_ids_for_product(
    session: AsyncSession,
    product_id: str | None,
    tenant_key: str,
) -> set[str] | None:
    if not product_id:
        return None

    return await ProductAgentAssignmentRepository().get_active_template_ids_for_product(session, product_id, tenant_key)


def filter_templates_by_ids[T](templates: Iterable[T], template_ids: set[str] | None) -> list[T]:
    if template_ids is None:
        return list(templates)
    return [t for t in templates if t.id in template_ids]
