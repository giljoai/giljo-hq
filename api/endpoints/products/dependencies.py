# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Dependencies for Product Endpoints - Handover 0127b

Provides dependency injection for ProductService.
"""

from fastapi import Depends

from api.dependencies import get_tenant_key
from giljo_mcp.database import DatabaseManager
from giljo_mcp.services import ProductService
from giljo_mcp.services.product_memory_service import ProductMemoryService
from giljo_mcp.services.product_vision_service import ProductVisionService


async def get_db_manager() -> DatabaseManager:
    """
    Get DatabaseManager instance from app state.

    Returns the database manager from the FastAPI application state.
    """
    # Get db_manager from application state (set during startup)
    from api.app_state import state

    return state.db_manager


async def get_product_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> ProductService:
    """
    Get ProductService instance with tenant isolation.

    Args:
        tenant_key: Tenant key from request context
        db_manager: Database manager instance

    Returns:
        ProductService instance configured for the current tenant
    """
    from api.app_state import state

    ws_manager = getattr(state, "websocket_manager", None)
    return ProductService(db_manager=db_manager, tenant_key=tenant_key, websocket_manager=ws_manager)


async def get_product_vision_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> ProductVisionService:
    """
    Get ProductVisionService instance with tenant isolation.

    Args:
        tenant_key: Tenant key from request context
        db_manager: Database manager instance

    Returns:
        ProductVisionService instance configured for the current tenant
    """
    return ProductVisionService(db_manager=db_manager, tenant_key=tenant_key)


async def get_product_memory_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> ProductMemoryService:
    """Get ProductMemoryService instance with tenant isolation.

    BE-5022a: Added dependency for memory entry queries.

    Args:
        tenant_key: Tenant key from request context
        db_manager: Database manager instance

    Returns:
        ProductMemoryService instance configured for the current tenant
    """
    return ProductMemoryService(db_manager=db_manager, tenant_key=tenant_key)
