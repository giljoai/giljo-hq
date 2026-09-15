# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging

from sqlalchemy import select

from giljo_mcp.database import DatabaseManager, tenant_session_context
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models.auth import User
from giljo_mcp.services.notification_service import NotificationService


logger = logging.getLogger(__name__)

CONTEXT_TUNING_DUE_DEDUPE_KEY = "system.context_tuning_due"


async def _resolve_active_user_id(db_manager: DatabaseManager, tenant_key: str) -> str | None:
    async with db_manager.get_session_async() as session:
        with tenant_session_context(session, tenant_key):
            user_id = (
                await session.execute(select(User.id).where(User.tenant_key == tenant_key, User.is_active).limit(1))
            ).scalar_one_or_none()
    return str(user_id) if user_id else None


async def compute_context_tuning_due(db_manager: DatabaseManager, tenant_key: str) -> dict | None:
    from giljo_mcp.services.product_service import ProductService
    from giljo_mcp.services.product_tuning_service import ProductTuningService

    product_service = ProductService(db_manager=db_manager, tenant_key=tenant_key)
    product = await product_service.get_default_product(eager_load=False)
    if product is None:
        return None

    user_id = await _resolve_active_user_id(db_manager, tenant_key)
    if not user_id:
        return None

    tuning_service = ProductTuningService(db_manager=db_manager, tenant_key=tenant_key)
    try:
        staleness = await tuning_service.check_tuning_staleness(product_id=str(product.id), user_id=user_id)
    except ResourceNotFoundError:
        return None
    if not staleness.get("enabled"):
        return None
    if not staleness.get("is_stale"):
        return None

    return {
        "product_id": str(product.id),
        "product_name": product.name,
        "projects_since_tune": int(staleness.get("projects_since_tune", 0) or 0),
    }


async def emit_context_tuning_due_banner(
    service: NotificationService,
    tenant_key: str,
    due: dict | None,
    *,
    tools_route: str,
) -> None:
    if due is None:
        await service.resolve_by_dedupe_key(tenant_key, CONTEXT_TUNING_DUE_DEDUPE_KEY)
        return

    count = due["projects_since_tune"]
    await service.upsert_by_dedupe_key(
        tenant_key=tenant_key,
        user_id=None,
        notification_type="system.context_tuning_due",
        severity="info",
        title="Time for a context review",
        body=(
            f"{due['product_name']} has had {count} project{'s' if count != 1 else ''} "
            "complete since its last context review — tune it so your agents stay current."
        ),
        dedupe_key=CONTEXT_TUNING_DUE_DEDUPE_KEY,
        surface="banner",
        role_filter=None,
        cta_label="Review context",
        cta_route=tools_route,
        dismissible=True,
        resurface_after_hours=None,
        payload={
            "product_id": due["product_id"],
            "product_name": due["product_name"],
            "projects_since_tune": count,
        },
    )
