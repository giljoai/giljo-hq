# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from fastapi import Depends

from api.dependencies import get_tenant_key
from giljo_mcp.database import DatabaseManager
from giljo_mcp.services import AuthService, UserService
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.message_routing_service import MessageRoutingService
from giljo_mcp.services.notification_service import NotificationService
from giljo_mcp.services.product_service import ProductService
from giljo_mcp.services.roadmap_service import RoadmapService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.services.task_service import TaskService
from giljo_mcp.tenant import TenantManager


async def get_db_manager() -> DatabaseManager:
    from api.app_state import state

    return state.db_manager


async def get_user_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> UserService:
    return UserService(db_manager=db_manager, tenant_key=tenant_key)


async def get_auth_service(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> AuthService:
    return AuthService(db_manager=db_manager)


async def get_tenant_manager() -> TenantManager:
    from api.app_state import state

    return state.tenant_manager


async def get_websocket_manager():
    from api.app_state import state

    return state.websocket_manager


async def get_task_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
    tenant_manager: TenantManager = Depends(get_tenant_manager),
    websocket_manager=Depends(get_websocket_manager),
) -> TaskService:
    tenant_manager.set_current_tenant(tenant_key)
    return TaskService(db_manager=db_manager, tenant_manager=tenant_manager, websocket_manager=websocket_manager)


async def get_roadmap_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
    tenant_manager: TenantManager = Depends(get_tenant_manager),
) -> RoadmapService:
    tenant_manager.set_current_tenant(tenant_key)
    return RoadmapService(db_manager=db_manager, tenant_manager=tenant_manager)


async def get_sequence_run_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
    tenant_manager: TenantManager = Depends(get_tenant_manager),
    websocket_manager=Depends(get_websocket_manager),
) -> SequenceRunService:
    tenant_manager.set_current_tenant(tenant_key)
    return SequenceRunService(db_manager=db_manager, tenant_manager=tenant_manager, websocket_manager=websocket_manager)


async def get_message_routing_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
    tenant_manager: TenantManager = Depends(get_tenant_manager),
    websocket_manager=Depends(get_websocket_manager),
) -> MessageRoutingService:
    tenant_manager.set_current_tenant(tenant_key)
    return MessageRoutingService(
        db_manager=db_manager, tenant_manager=tenant_manager, websocket_manager=websocket_manager
    )


async def get_notification_service(
    db_manager: DatabaseManager = Depends(get_db_manager),
    websocket_manager=Depends(get_websocket_manager),
) -> NotificationService:
    return NotificationService(db_manager=db_manager, websocket_manager=websocket_manager)


async def get_comm_thread_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
    tenant_manager: TenantManager = Depends(get_tenant_manager),
) -> CommThreadService:
    tenant_manager.set_current_tenant(tenant_key)
    return CommThreadService(db_manager=db_manager, tenant_manager=tenant_manager)


async def get_product_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
    websocket_manager=Depends(get_websocket_manager),
) -> ProductService:
    return ProductService(db_manager=db_manager, tenant_key=tenant_key, websocket_manager=websocket_manager)
