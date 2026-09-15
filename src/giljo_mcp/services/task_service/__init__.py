# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.repositories.task_repository import TaskRepository
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.task_conversion_service import TaskConversionService
from giljo_mcp.services.task_service._lifecycle_mixin import _TaskLifecycleMixin
from giljo_mcp.services.task_service._mcp_adapter_mixin import McpAdapterMixin
from giljo_mcp.services.task_service._mutation_mixin import (
    _ALLOWED_TASK_UPDATE_FIELDS as _ALLOWED_TASK_UPDATE_FIELDS,
)
from giljo_mcp.services.task_service._mutation_mixin import _TaskMutationMixin
from giljo_mcp.services.task_service._query_mixin import _TaskQueryMixin
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


class TaskService(McpAdapterMixin, _TaskMutationMixin, _TaskLifecycleMixin, _TaskQueryMixin):

    def __init__(
        self,
        db_manager: DatabaseManager = None,
        tenant_manager: TenantManager = None,
        session: AsyncSession | None = None,
        websocket_manager: Any | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._session = session
        self._websocket_manager = websocket_manager
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._repo = TaskRepository()
        self._conversion = TaskConversionService(db_manager, tenant_manager, session)

    def _get_session(self, tenant_key: str | None = None):
        return optional_tenant_session(
            self.db_manager, tenant_key or self.tenant_manager.get_current_tenant(), self._session
        )
