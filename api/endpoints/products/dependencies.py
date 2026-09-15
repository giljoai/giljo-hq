# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from fastapi import Depends

from api.dependencies import get_tenant_key
from giljo_mcp.database import DatabaseManager
from giljo_mcp.services import ProductService
from giljo_mcp.services.product_memory_service import ProductMemoryService
from giljo_mcp.services.product_vision_service import ProductVisionService


async def get_db_manager() -> DatabaseManager:
    from api.app_state import state

    return state.db_manager


async def get_product_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> ProductService:
    from api.app_state import state

    ws_manager = getattr(state, "websocket_manager", None)
    return ProductService(db_manager=db_manager, tenant_key=tenant_key, websocket_manager=ws_manager)


async def get_product_vision_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> ProductVisionService:
    return ProductVisionService(db_manager=db_manager, tenant_key=tenant_key)


async def get_product_memory_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> ProductMemoryService:
    return ProductMemoryService(db_manager=db_manager, tenant_key=tenant_key)
