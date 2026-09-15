# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from sqlalchemy import select

from giljo_mcp.models import Configuration
from giljo_mcp.system_prompts.service import (
    DEFAULT_ORCHESTRATOR_CONFIG_KEY,
    SystemPromptService,
)


@pytest.mark.asyncio
class TestSystemPromptServiceTenantScope:

    async def test_get_requires_tenant_key(self, db_manager, db_session):
        service = SystemPromptService(db_manager=db_manager)
        with pytest.raises(ValueError, match="tenant_key"):
            await service.get_orchestrator_prompt(tenant_key="", session=db_session)

    async def test_update_requires_tenant_key(self, db_manager, db_session):
        service = SystemPromptService(db_manager=db_manager)
        with pytest.raises(ValueError, match="tenant_key"):
            await service.update_orchestrator_prompt(
                tenant_key="",
                content="Some content",
                updated_by="admin@test",
                session=db_session,
            )

    async def test_reset_requires_tenant_key(self, db_manager, db_session):
        service = SystemPromptService(db_manager=db_manager)
        with pytest.raises(ValueError, match="tenant_key"):
            await service.reset_orchestrator_prompt(tenant_key="", session=db_session)

    async def test_update_writes_tenant_scoped_row(self, db_manager, db_session, test_tenant_key):
        service = SystemPromptService(db_manager=db_manager)

        result = await service.update_orchestrator_prompt(
            tenant_key=test_tenant_key,
            content="Tenant A custom prompt",
            updated_by="admin@a",
            session=db_session,
        )
        await db_session.commit()

        assert result.is_override is True
        assert result.content == "Tenant A custom prompt"

        stmt = select(Configuration).where(
            Configuration.key == DEFAULT_ORCHESTRATOR_CONFIG_KEY,
            Configuration.tenant_key == test_tenant_key,
        )
        row = (await db_session.execute(stmt)).scalar_one()
        assert row.tenant_key == test_tenant_key
        assert row.value["content"] == "Tenant A custom prompt"

        null_stmt = select(Configuration).where(
            Configuration.key == DEFAULT_ORCHESTRATOR_CONFIG_KEY,
            Configuration.tenant_key.is_(None),
        )
        null_row = (await db_session.execute(null_stmt)).scalar_one_or_none()
        assert null_row is None

    async def test_get_returns_default_when_no_override(self, db_manager, db_session, test_tenant_key):
        service = SystemPromptService(db_manager=db_manager)
        result = await service.get_orchestrator_prompt(tenant_key=test_tenant_key, session=db_session)
        assert result.is_override is False
        assert result.content

    async def test_tenant_isolation_between_a_and_b(self, db_manager, db_session):
        service = SystemPromptService(db_manager=db_manager)
        tenant_a = "tk_tenant_a_sec5b"
        tenant_b = "tk_tenant_b_sec5b"

        await service.update_orchestrator_prompt(
            tenant_key=tenant_a,
            content="A's private prompt",
            updated_by="admin@a",
            session=db_session,
        )
        await db_session.commit()

        a_result = await service.get_orchestrator_prompt(tenant_key=tenant_a, session=db_session)
        b_result = await service.get_orchestrator_prompt(tenant_key=tenant_b, session=db_session)

        assert a_result.is_override is True
        assert a_result.content == "A's private prompt"
        assert b_result.is_override is False
        assert "A's private prompt" not in b_result.content

    async def test_reset_deletes_only_that_tenant_override(self, db_manager, db_session):
        service = SystemPromptService(db_manager=db_manager)
        tenant_a = "tk_tenant_reset_a"
        tenant_b = "tk_tenant_reset_b"

        await service.update_orchestrator_prompt(
            tenant_key=tenant_a, content="A override", updated_by="a", session=db_session
        )
        await service.update_orchestrator_prompt(
            tenant_key=tenant_b, content="B override", updated_by="b", session=db_session
        )
        await db_session.commit()

        await service.reset_orchestrator_prompt(tenant_key=tenant_a, session=db_session)
        await db_session.commit()

        a_result = await service.get_orchestrator_prompt(tenant_key=tenant_a, session=db_session)
        b_result = await service.get_orchestrator_prompt(tenant_key=tenant_b, session=db_session)
        assert a_result.is_override is False
        assert b_result.is_override is True
        assert b_result.content == "B override"
