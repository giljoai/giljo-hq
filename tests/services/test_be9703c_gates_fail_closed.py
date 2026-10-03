# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from giljo_mcp.exceptions import DatabaseError, ResourceNotFoundError
from giljo_mcp.services.task_service._handover_guards import handover_state
from giljo_mcp.services.task_type_immutability import require_unchanged_task_type
from giljo_mcp.tools._memory_helpers import resolve_git_closeout_rule


def _db_down() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception("connection refused"))


@pytest.mark.asyncio
async def test_git_closeout_rule_lets_a_settings_read_fault_raise(monkeypatch):
    from giljo_mcp.services import settings_service

    class _Broken:
        def __init__(self, session, tenant_key):
            pass

        async def get_setting_value(self, category, key, default=None):
            raise _db_down()

    monkeypatch.setattr(settings_service, "SettingsService", _Broken)
    with pytest.raises(OperationalError):
        await resolve_git_closeout_rule(
            object(), "tenant", project_id=str(uuid4()), git_commits=None, no_code_changes=None
        )


@pytest.mark.asyncio
async def test_handover_guard_answers_not_found_only_for_not_found():
    async def _missing(_task_id):
        raise ResourceNotFoundError(message="Task not found", context={})

    async def _broken(_task_id):
        raise DatabaseError(message="Database operation failed", context={})

    assert await handover_state(_missing, "t-1") == (False, None)
    with pytest.raises(DatabaseError):
        await handover_state(_broken, "t-1")


@pytest.mark.asyncio
async def test_task_type_guard_answers_silence_only_for_not_found():
    async def _missing(_task_id):
        raise ResourceNotFoundError(message="Task not found", context={})

    async def _broken(_task_id):
        raise DatabaseError(message="Database operation failed", context={})

    await require_unchanged_task_type(_missing, "t-1", "HND")
    with pytest.raises(DatabaseError):
        await require_unchanged_task_type(_broken, "t-1", "HND")


@pytest.mark.asyncio
async def test_template_product_filter_does_not_fall_back_to_every_template(db_session, monkeypatch):
    from datetime import UTC, datetime

    from giljo_mcp.models.products import Product
    from giljo_mcp.models.templates import AgentTemplate
    from giljo_mcp.repositories.product_agent_assignment_repository import ProductAgentAssignmentRepository
    from giljo_mcp.tenant import TenantManager
    from giljo_mcp.tools.context_tools.get_agent_templates import get_agent_templates

    tenant_key = TenantManager.generate_tenant_key()
    product = Product(
        id=str(uuid4()),
        name=f"F4 product {uuid4().hex[:6]}",
        description="gate fixture",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(product)
    db_session.add(
        AgentTemplate(
            id=str(uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            name=f"implementer_{uuid4().hex[:6]}",
            role="Implementer",
            description="d",
            is_active=True,
        )
    )
    await db_session.commit()

    async def _boom(self, session, product_id, tenant_key):
        raise RuntimeError("transient connection reset")

    monkeypatch.setattr(ProductAgentAssignmentRepository, "get_active_template_ids_for_product", _boom)
    with pytest.raises(RuntimeError):
        await get_agent_templates(
            product_id=product.id, tenant_key=tenant_key, detail="basic", _test_session=db_session
        )
