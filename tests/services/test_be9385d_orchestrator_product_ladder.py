# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from giljo_mcp.models import Configuration
from giljo_mcp.system_prompts.service import (
    DEFAULT_ORCHESTRATOR_CONFIG_KEY,
    SystemPromptService,
    product_orchestrator_config_key,
)


TENANT_TEXT = "TENANT-WIDE orchestrator seed. My style everywhere."
PRODUCT_TEXT = "PRODUCT-SCOPED orchestrator seed. This product only."


@pytest.mark.asyncio
class TestResolutionLadder:

    async def test_product_override_wins_over_tenant_override(self, db_manager, db_session, test_tenant_key):
        service = SystemPromptService(db_manager=db_manager)
        product_id = str(uuid.uuid4())

        await service.update_orchestrator_prompt(
            tenant_key=test_tenant_key, content=TENANT_TEXT, updated_by="admin", session=db_session
        )
        await service.update_orchestrator_prompt(
            tenant_key=test_tenant_key,
            content=PRODUCT_TEXT,
            updated_by="admin",
            product_id=product_id,
            session=db_session,
        )
        await db_session.commit()

        result = await service.get_orchestrator_prompt(
            tenant_key=test_tenant_key, product_id=product_id, session=db_session
        )
        assert result.content == PRODUCT_TEXT
        assert result.is_override is True
        assert result.scope == "product"

    async def test_tenant_override_is_byte_identical_when_no_product_override(
        self, db_manager, db_session, test_tenant_key
    ):
        service = SystemPromptService(db_manager=db_manager)
        await service.update_orchestrator_prompt(
            tenant_key=test_tenant_key, content=TENANT_TEXT, updated_by="admin", session=db_session
        )
        await db_session.commit()

        without_product = await service.get_orchestrator_prompt(tenant_key=test_tenant_key, session=db_session)
        with_product = await service.get_orchestrator_prompt(
            tenant_key=test_tenant_key, product_id=str(uuid.uuid4()), session=db_session
        )

        assert with_product.content == TENANT_TEXT
        assert with_product.content == without_product.content
        assert with_product.is_override is True
        assert with_product.scope == "tenant"

    async def test_seed_is_byte_identical_when_neither_override_exists(self, db_manager, db_session, test_tenant_key):
        service = SystemPromptService(db_manager=db_manager)

        without_product = await service.get_orchestrator_prompt(tenant_key=test_tenant_key, session=db_session)
        with_product = await service.get_orchestrator_prompt(
            tenant_key=test_tenant_key, product_id=str(uuid.uuid4()), session=db_session
        )

        assert with_product.content == without_product.content
        assert with_product.is_override is False
        assert with_product.scope == "default"
        assert with_product.content

    async def test_product_override_does_not_leak_to_another_product(self, db_manager, db_session, test_tenant_key):
        service = SystemPromptService(db_manager=db_manager)
        product_a, product_b = str(uuid.uuid4()), str(uuid.uuid4())

        await service.update_orchestrator_prompt(
            tenant_key=test_tenant_key, content=TENANT_TEXT, updated_by="admin", session=db_session
        )
        await service.update_orchestrator_prompt(
            tenant_key=test_tenant_key,
            content=PRODUCT_TEXT,
            updated_by="admin",
            product_id=product_a,
            session=db_session,
        )
        await db_session.commit()

        a_result = await service.get_orchestrator_prompt(
            tenant_key=test_tenant_key, product_id=product_a, session=db_session
        )
        b_result = await service.get_orchestrator_prompt(
            tenant_key=test_tenant_key, product_id=product_b, session=db_session
        )
        assert a_result.content == PRODUCT_TEXT
        assert b_result.content == TENANT_TEXT


@pytest.mark.asyncio
class TestProductRowStorage:

    async def test_product_row_uses_namespaced_key_and_leaves_tenant_row_alone(
        self, db_manager, db_session, test_tenant_key
    ):
        service = SystemPromptService(db_manager=db_manager)
        product_id = str(uuid.uuid4())

        await service.update_orchestrator_prompt(
            tenant_key=test_tenant_key, content=TENANT_TEXT, updated_by="admin", session=db_session
        )
        await service.update_orchestrator_prompt(
            tenant_key=test_tenant_key,
            content=PRODUCT_TEXT,
            updated_by="admin",
            product_id=product_id,
            session=db_session,
        )
        await db_session.commit()

        expected_key = product_orchestrator_config_key(product_id)
        assert expected_key == f"{DEFAULT_ORCHESTRATOR_CONFIG_KEY}:{product_id}"

        rows = (
            (await db_session.execute(select(Configuration).where(Configuration.tenant_key == test_tenant_key)))
            .scalars()
            .all()
        )
        by_key = {row.key: row for row in rows}
        assert by_key[DEFAULT_ORCHESTRATOR_CONFIG_KEY].value["content"] == TENANT_TEXT
        assert by_key[expected_key].value["content"] == PRODUCT_TEXT

    async def test_product_override_is_tenant_scoped(self, db_manager, db_session):
        service = SystemPromptService(db_manager=db_manager)
        product_id = str(uuid.uuid4())
        tenant_a, tenant_b = "tk_be9385d_a", "tk_be9385d_b"

        await service.update_orchestrator_prompt(
            tenant_key=tenant_a,
            content="A's product prompt",
            updated_by="a",
            product_id=product_id,
            session=db_session,
        )
        await db_session.commit()

        a_result = await service.get_orchestrator_prompt(tenant_key=tenant_a, product_id=product_id, session=db_session)
        b_result = await service.get_orchestrator_prompt(tenant_key=tenant_b, product_id=product_id, session=db_session)
        assert a_result.content == "A's product prompt"
        assert b_result.is_override is False
        assert "A's product prompt" not in b_result.content

    async def test_reset_at_product_scope_falls_back_to_tenant_and_keeps_tenant_row(
        self, db_manager, db_session, test_tenant_key
    ):
        service = SystemPromptService(db_manager=db_manager)
        product_id = str(uuid.uuid4())

        await service.update_orchestrator_prompt(
            tenant_key=test_tenant_key, content=TENANT_TEXT, updated_by="admin", session=db_session
        )
        await service.update_orchestrator_prompt(
            tenant_key=test_tenant_key,
            content=PRODUCT_TEXT,
            updated_by="admin",
            product_id=product_id,
            session=db_session,
        )
        await db_session.commit()

        after_reset = await service.reset_orchestrator_prompt(
            tenant_key=test_tenant_key, product_id=product_id, session=db_session
        )
        await db_session.commit()

        assert after_reset.content == TENANT_TEXT
        assert after_reset.scope == "tenant"

        tenant_row = (
            await db_session.execute(
                select(Configuration).where(
                    Configuration.tenant_key == test_tenant_key,
                    Configuration.key == DEFAULT_ORCHESTRATOR_CONFIG_KEY,
                )
            )
        ).scalar_one()
        assert tenant_row.value["content"] == TENANT_TEXT

        product_row = (
            await db_session.execute(
                select(Configuration).where(
                    Configuration.tenant_key == test_tenant_key,
                    Configuration.key == product_orchestrator_config_key(product_id),
                )
            )
        ).scalar_one_or_none()
        assert product_row is None

    async def test_tenant_reset_does_not_delete_product_overrides(self, db_manager, db_session, test_tenant_key):
        service = SystemPromptService(db_manager=db_manager)
        product_id = str(uuid.uuid4())

        await service.update_orchestrator_prompt(
            tenant_key=test_tenant_key, content=TENANT_TEXT, updated_by="admin", session=db_session
        )
        await service.update_orchestrator_prompt(
            tenant_key=test_tenant_key,
            content=PRODUCT_TEXT,
            updated_by="admin",
            product_id=product_id,
            session=db_session,
        )
        await db_session.commit()

        await service.reset_orchestrator_prompt(tenant_key=test_tenant_key, session=db_session)
        await db_session.commit()

        still_product = await service.get_orchestrator_prompt(
            tenant_key=test_tenant_key, product_id=product_id, session=db_session
        )
        assert still_product.content == PRODUCT_TEXT
        assert still_product.scope == "product"


@pytest.mark.asyncio
class TestProductIdValidation:

    @pytest.mark.parametrize(
        "bad_product_id",
        [
            "not-a-uuid",
            "x" * 40,
            "../../etc/passwd",
            "abc def",
        ],
    )
    async def test_malformed_product_id_is_rejected(self, db_manager, db_session, test_tenant_key, bad_product_id):
        service = SystemPromptService(db_manager=db_manager)
        with pytest.raises(ValueError, match="product_id"):
            await service.get_orchestrator_prompt(
                tenant_key=test_tenant_key, product_id=bad_product_id, session=db_session
            )

    async def test_blank_product_id_is_treated_as_no_product(self, db_manager, db_session, test_tenant_key):
        service = SystemPromptService(db_manager=db_manager)
        await service.update_orchestrator_prompt(
            tenant_key=test_tenant_key, content=TENANT_TEXT, updated_by="admin", session=db_session
        )
        await db_session.commit()

        for empty in ("", "   ", None):
            result = await service.get_orchestrator_prompt(
                tenant_key=test_tenant_key, product_id=empty, session=db_session
            )
            assert result.content == TENANT_TEXT
            assert result.scope == "tenant"
