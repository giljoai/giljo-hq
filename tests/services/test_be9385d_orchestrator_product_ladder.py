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
    ProductRequiredError,
    SystemPromptService,
    product_orchestrator_config_key,
)


LEFTOVER_TENANT_TEXT = "ACCOUNT-WIDE row left behind by an old version."
PRODUCT_TEXT = "PRODUCT-SCOPED orchestrator seed. This product only."


async def _config_rows(db_session, tenant_key: str) -> dict[str, Configuration]:
    rows = (await db_session.execute(select(Configuration).where(Configuration.tenant_key == tenant_key))).scalars()
    return {row.key: row for row in rows}


@pytest.mark.asyncio
class TestResolution:

    async def test_a_product_resolves_to_its_own_row(self, db_manager, db_session, test_tenant_key):
        service = SystemPromptService(db_manager=db_manager)
        product_id = str(uuid.uuid4())
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

    async def test_a_product_without_a_row_gets_the_seed_even_if_a_stale_account_wide_row_exists(
        self, db_manager, db_session, test_tenant_key
    ):
        db_session.add(
            Configuration(
                tenant_key=test_tenant_key,
                key=DEFAULT_ORCHESTRATOR_CONFIG_KEY,
                value={"content": LEFTOVER_TENANT_TEXT},
                category="system",
            )
        )
        await db_session.commit()
        service = SystemPromptService(db_manager=db_manager)

        result = await service.get_orchestrator_prompt(
            tenant_key=test_tenant_key, product_id=str(uuid.uuid4()), session=db_session
        )
        no_product = await service.get_orchestrator_prompt(tenant_key=test_tenant_key, session=db_session)

        assert result.is_override is False
        assert result.scope == "default"
        assert LEFTOVER_TENANT_TEXT not in result.content
        assert no_product.content == result.content
        assert result.content

    async def test_a_product_override_does_not_leak_to_another_product(self, db_manager, db_session, test_tenant_key):
        service = SystemPromptService(db_manager=db_manager)
        product_a, product_b = str(uuid.uuid4()), str(uuid.uuid4())
        await service.update_orchestrator_prompt(
            tenant_key=test_tenant_key,
            content=PRODUCT_TEXT,
            updated_by="admin",
            product_id=product_a,
            session=db_session,
        )
        await db_session.commit()

        b_result = await service.get_orchestrator_prompt(
            tenant_key=test_tenant_key, product_id=product_b, session=db_session
        )
        assert b_result.is_override is False
        assert PRODUCT_TEXT not in b_result.content


@pytest.mark.asyncio
class TestProductRowStorage:

    async def test_product_row_uses_the_namespaced_key(self, db_manager, db_session, test_tenant_key):
        service = SystemPromptService(db_manager=db_manager)
        product_id = str(uuid.uuid4())
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
        rows = await _config_rows(db_session, test_tenant_key)
        assert set(rows) == {expected_key}
        assert rows[expected_key].value["content"] == PRODUCT_TEXT

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

    async def test_reset_returns_that_product_to_the_seed_and_leaves_other_products_alone(
        self, db_manager, db_session, test_tenant_key
    ):
        service = SystemPromptService(db_manager=db_manager)
        product_a, product_b = str(uuid.uuid4()), str(uuid.uuid4())
        for product_id in (product_a, product_b):
            await service.update_orchestrator_prompt(
                tenant_key=test_tenant_key,
                content=f"text for {product_id}",
                updated_by="admin",
                product_id=product_id,
                session=db_session,
            )
        await db_session.commit()

        after_reset = await service.reset_orchestrator_prompt(
            tenant_key=test_tenant_key, product_id=product_a, session=db_session
        )
        await db_session.commit()

        assert after_reset.is_override is False
        assert after_reset.scope == "default"
        assert set(await _config_rows(db_session, test_tenant_key)) == {product_orchestrator_config_key(product_b)}
        still_b = await service.get_orchestrator_prompt(
            tenant_key=test_tenant_key, product_id=product_b, session=db_session
        )
        assert still_b.content == f"text for {product_b}"


@pytest.mark.asyncio
class TestWritesNeedAProduct:

    @pytest.mark.parametrize("missing", [None, "", "   "])
    async def test_save_additions_without_a_product_is_refused_and_writes_nothing(
        self, db_manager, db_session, test_tenant_key, missing
    ):
        service = SystemPromptService(db_manager=db_manager)
        with pytest.raises(ProductRequiredError, match="product_id is required"):
            await service.update_orchestrator_additions(
                tenant_key=test_tenant_key, additions="x", updated_by="admin", product_id=missing, session=db_session
            )
        assert await _config_rows(db_session, test_tenant_key) == {}

    @pytest.mark.parametrize("missing", [None, "", "   "])
    async def test_save_replacement_without_a_product_is_refused_and_writes_nothing(
        self, db_manager, db_session, test_tenant_key, missing
    ):
        service = SystemPromptService(db_manager=db_manager)
        with pytest.raises(ProductRequiredError):
            await service.update_orchestrator_prompt(
                tenant_key=test_tenant_key, content="x", updated_by="admin", product_id=missing, session=db_session
            )
        assert await _config_rows(db_session, test_tenant_key) == {}

    @pytest.mark.parametrize("missing", [None, "", "   "])
    async def test_reset_without_a_product_is_refused_and_deletes_nothing(
        self, db_manager, db_session, test_tenant_key, missing
    ):
        service = SystemPromptService(db_manager=db_manager)
        product_id = str(uuid.uuid4())
        await service.update_orchestrator_prompt(
            tenant_key=test_tenant_key,
            content=PRODUCT_TEXT,
            updated_by="admin",
            product_id=product_id,
            session=db_session,
        )
        await db_session.commit()

        with pytest.raises(ProductRequiredError):
            await service.reset_orchestrator_prompt(tenant_key=test_tenant_key, product_id=missing, session=db_session)
        assert set(await _config_rows(db_session, test_tenant_key)) == {product_orchestrator_config_key(product_id)}


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

    async def test_blank_product_id_on_a_read_means_no_product_context_and_gets_the_seed(
        self, db_manager, db_session, test_tenant_key
    ):
        service = SystemPromptService(db_manager=db_manager)

        for empty in ("", "   ", None):
            result = await service.get_orchestrator_prompt(
                tenant_key=test_tenant_key, product_id=empty, session=db_session
            )
            assert result.is_override is False
            assert result.scope == "default"
