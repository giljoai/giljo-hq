# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Product activate/deactivate for the update_product_context MCP tool (BE-9502a).

Split out of vision_analysis.py (already at its 800-line file-size cap) rather
than grown inline: activation is a distinct concern from vision-extraction's
merge-write. It enforces the per-tenant single-active-product invariant via
ProductLifecycleService (deactivating any sibling), which is lifecycle
behavior, not a plain column set -- routing it through the generic field
allowlist would repeat the S1b sibling-deactivate bypass bug.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager


async def apply_activation_state(
    product_id: str,
    tenant_key: str,
    is_active: bool,
    db_manager: DatabaseManager | None,
    websocket_manager: Any,
    test_session: AsyncSession | None,
) -> dict[str, Any]:
    """Activate/deactivate via the SAME owning writer the REST
    POST /api/products/{id}/activate|deactivate endpoints use
    (ProductService.activate_product / deactivate_product).
    """
    from giljo_mcp.services.product_service import ProductService

    product_service = ProductService(
        db_manager=db_manager,
        tenant_key=tenant_key,
        websocket_manager=websocket_manager,
        test_session=test_session,
    )
    if is_active:
        activated = await product_service.activate_product(product_id)
        return {"is_active": True, "product_id": str(activated.id)}
    deactivated = await product_service.deactivate_product(product_id)
    return {"is_active": False, "product_id": str(deactivated.id)}
