# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Dependencies for User and Auth Endpoints - Handover 0322 Phase 1C/2C

Provides dependency injection for UserService and AuthService.
"""

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
    """
    Get DatabaseManager instance from app state.

    Returns the database manager from the FastAPI application state.
    """
    # Get db_manager from application state (set during startup)
    from api.app_state import state

    return state.db_manager


async def get_user_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> UserService:
    """
    Get UserService instance with tenant isolation.

    Args:
        tenant_key: Tenant key from request context
        db_manager: Database manager instance

    Returns:
        UserService instance configured for the current tenant
    """
    return UserService(db_manager=db_manager, tenant_key=tenant_key)


async def get_auth_service(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> AuthService:
    """
    Get AuthService instance (no tenant isolation for auth operations).

    Args:
        db_manager: Database manager instance

    Returns:
        AuthService instance for authentication operations
    """
    return AuthService(db_manager=db_manager)


async def get_tenant_manager() -> TenantManager:
    """
    Get TenantManager instance from app state.

    Returns the tenant manager from the FastAPI application state.
    """
    # Get tenant_manager from application state (set during startup)
    from api.app_state import state

    return state.tenant_manager


async def get_websocket_manager():
    """Get WebSocketManager instance from app state."""
    from api.app_state import state

    return state.websocket_manager


async def get_task_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
    tenant_manager: TenantManager = Depends(get_tenant_manager),
    websocket_manager=Depends(get_websocket_manager),
) -> TaskService:
    """
    Get TaskService instance for task management.

    Sets the tenant context before returning the service instance.

    FE-9274: was missing ``websocket_manager`` (unlike its sibling dependencies
    below -- SequenceRunService, MessageRoutingService, ProductService all
    receive it). TaskService's own broadcast calls silently no-op when
    ``self._websocket_manager is None``, so every REST task mutation (create,
    update, status change) landed in the DB but never told a connected
    dashboard tab to refresh its task list -- BE-9246's "stale dashboard
    tiles" bug, but for tasks instead of agent status.

    Args:
        tenant_key: Tenant key from request context
        db_manager: Database manager instance
        tenant_manager: Tenant manager instance
        websocket_manager: WebSocket manager for real-time task:created/task:updated events

    Returns:
        TaskService instance for task operations
    """
    # Set tenant context for this request
    tenant_manager.set_current_tenant(tenant_key)
    return TaskService(db_manager=db_manager, tenant_manager=tenant_manager, websocket_manager=websocket_manager)


async def get_roadmap_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
    tenant_manager: TenantManager = Depends(get_tenant_manager),
) -> RoadmapService:
    """
    Get RoadmapService instance for the Roadmapping Pane (FE-6022a).

    Sets the tenant context before returning the service instance. The service
    resolves the active product from the tenant_key threaded explicitly into
    each call.
    """
    tenant_manager.set_current_tenant(tenant_key)
    return RoadmapService(db_manager=db_manager, tenant_manager=tenant_manager)


async def get_sequence_run_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
    tenant_manager: TenantManager = Depends(get_tenant_manager),
    websocket_manager=Depends(get_websocket_manager),
) -> SequenceRunService:
    """Get SequenceRunService for the Sequential Multi-Project Runner (BE-6131a)."""
    tenant_manager.set_current_tenant(tenant_key)
    return SequenceRunService(db_manager=db_manager, tenant_manager=tenant_manager, websocket_manager=websocket_manager)


async def get_message_routing_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
    tenant_manager: TenantManager = Depends(get_tenant_manager),
    websocket_manager=Depends(get_websocket_manager),
) -> MessageRoutingService:
    """Get MessageRoutingService instance for message sending, routing, and broadcasting."""
    tenant_manager.set_current_tenant(tenant_key)
    return MessageRoutingService(
        db_manager=db_manager, tenant_manager=tenant_manager, websocket_manager=websocket_manager
    )


async def get_notification_service(
    db_manager: DatabaseManager = Depends(get_db_manager),
    websocket_manager=Depends(get_websocket_manager),
) -> NotificationService:
    """Get NotificationService instance.

    Tenant scoping is applied per-call via the explicit ``tenant_key`` argument
    threaded from the authenticated user, so this dependency itself carries no
    tenant state.
    """
    return NotificationService(db_manager=db_manager, websocket_manager=websocket_manager)


async def get_comm_thread_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
    tenant_manager: TenantManager = Depends(get_tenant_manager),
) -> CommThreadService:
    """Get CommThreadService for the Agent Message Hub REST adapter (BE-6054ef)."""
    tenant_manager.set_current_tenant(tenant_key)
    return CommThreadService(db_manager=db_manager, tenant_manager=tenant_manager)


async def get_product_service(
    tenant_key: str = Depends(get_tenant_key),
    db_manager: DatabaseManager = Depends(get_db_manager),
    websocket_manager=Depends(get_websocket_manager),
) -> ProductService:
    """
    Get ProductService instance with tenant isolation.

    Args:
        tenant_key: Tenant key from request context
        db_manager: Database manager instance
        websocket_manager: WebSocket manager for real-time events

    Returns:
        ProductService instance configured for the current tenant
    """
    return ProductService(db_manager=db_manager, tenant_key=tenant_key, websocket_manager=websocket_manager)
