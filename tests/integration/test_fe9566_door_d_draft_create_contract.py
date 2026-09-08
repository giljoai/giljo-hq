# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
FE-9566: the create contract the onboarding "existing codebase" door depends on.

The tour's door D pre-creates an EMPTY-NAMED product for the agent to fill in.
Two properties of ``create_product`` decide whether that door works on a second
visit, and neither is obvious from the door's own code, so they are pinned here.

Together they decide whether the door works on a second visit: that visit's
create is REJECTED, and until the fix that shipped alongside this file the
rejection was swallowed by an empty catch, so a failed create was
indistinguishable from one that never ran.

These are characterization tests. They assert what the service genuinely does
today, so that any later change to either property shows up as a failure here
rather than as a silently dead onboarding door.
"""

from uuid import uuid4

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.product_service import ProductService


@pytest.mark.asyncio
class TestDoorDDraftCreateContract:
    """The two create_product properties door D's behaviour hangs on."""

    async def test_a_new_product_is_shown_even_when_it_has_no_name(self, db_manager):
        """
        FE-9524/D1 redefined is_active as "shown as a tab", and create_product
        sets it True for every product including a nameless draft.

        This is correct in itself, but it means a freshly created door D draft
        can never match a predicate of the form ``not is_active and not name``.
        Three call sites still used that older "is_active means THE active
        product" reading, so none of them could see a draft they were written to
        find: the tour's adopt branch, its abandoned-draft cleanup hatch, and the
        QA harness's own draft discovery.
        """
        service = ProductService(db_manager, str(uuid4()))

        draft = await service.create_product(name="")

        assert draft.is_active is True, (
            "a nameless door D draft is created SHOWN; any 'not is_active and not name' "
            "predicate looking for it will therefore never match"
        )
        assert draft.name == ""

    async def test_a_second_nameless_draft_is_rejected_as_a_duplicate(self, db_manager):
        """
        create_product's uniqueness check is ``get_by_name(tenant_key, name)``,
        which filters on deleted_at only and compares the name exactly. The empty
        string is a name like any other to that query, so a tenant can hold only
        ONE nameless product at a time.

        Door D therefore fails on its second visit for as long as the first
        draft is still around, which is exactly what the harness ran into.
        """
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        first = await service.create_product(name="")
        assert first.is_active is True

        with pytest.raises(ValidationError) as rejected:
            await service.create_product(name="")

        assert "already exists" in str(rejected.value)

    async def test_the_named_fallback_collides_the_same_way(self, db_manager):
        """
        The door falls back to the literal name "My product" when the empty-name
        create is refused. That fallback is subject to the identical uniqueness
        rule, so once a "My product" is also lying around BOTH creates fail and
        the door has nothing left to try.
        """
        tenant_key = str(uuid4())
        service = ProductService(db_manager, tenant_key)

        await service.create_product(name="My product")

        with pytest.raises(ValidationError):
            await service.create_product(name="My product")

    async def test_the_rejection_does_not_apply_across_tenants(self, db_manager):
        """
        Sanity check on the isolation the uniqueness rule is scoped by: one
        tenant's nameless draft must not block another tenant's door D. Without
        this, the two tests above would also pass if the query were leaking
        across tenants, which would be a far worse defect than the one they pin.
        """
        first_service = ProductService(db_manager, str(uuid4()))
        second_service = ProductService(db_manager, str(uuid4()))

        await first_service.create_product(name="")
        other_tenant_draft = await second_service.create_product(name="")

        assert other_tenant_draft.name == ""
