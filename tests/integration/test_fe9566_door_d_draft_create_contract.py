# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.product_service import ProductService


@pytest.mark.asyncio
class TestDoorDDraftCreateContract:

    async def test_a_new_product_is_shown_even_when_it_has_no_name(self, db_manager):
        service = ProductService(db_manager, str(uuid4()))

        draft = await service.create_product(name="")

        assert draft.is_active is True, (
            "a nameless door D draft is created SHOWN; any 'not is_active and not name' "
            "predicate looking for it will therefore never match"
        )
        assert draft.name == ""

    async def test_a_second_nameless_draft_is_rejected_as_a_duplicate(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        first = await service.create_product(name="")
        assert first.is_active is True

        with pytest.raises(ValidationError) as rejected:
            await service.create_product(name="")

        assert "already exists" in str(rejected.value)

    async def test_the_named_fallback_collides_the_same_way(self, db_manager):
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        await service.create_product(name="My product")

        with pytest.raises(ValidationError):
            await service.create_product(name="My product")

    async def test_the_rejection_does_not_apply_across_tenants(self, db_manager):
        first_service = ProductService(db_manager, str(uuid4()))
        second_service = ProductService(db_manager, str(uuid4()))

        await first_service.create_product(name="")
        other_tenant_draft = await second_service.create_product(name="")

        assert other_tenant_draft.name == ""
