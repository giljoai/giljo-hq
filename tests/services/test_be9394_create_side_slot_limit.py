# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9394: the active-slot cap is enforced on the CREATE path, not only on update.

``validate_active_agent_limit`` had exactly ONE caller — the update path. That was
sufficient only because every new template was born tenant-INACTIVE, so the single
route to "active" ran through the update gate. BE-9391 made creation send
``is_active: true`` (the ruled fix for an agent that could not be activated at all),
which turned that implicit dependency into a real bypass: a user could exceed
USER_MANAGED_AGENT_LIMIT by creating rather than toggling.

Past 16 active roles the export cap and — since BE-9385a R1 — the roster cap both
truncate silently, which is the "installed but unspawnable" class R1 unified those
caps to kill. So this is not a cosmetic limit.

The fix calls the SAME validator with the SAME error contract the update path uses
(``ProjectStateError`` -> HTTP 409). The validator already accepts a not-yet-persisted
template id — ``test_be9211_active_slot_limit.py`` pins that shape with its own
``candidate_id = str(uuid4())`` — so nothing new is invented here.

Update-path behaviour is deliberately NOT re-tested here; BE-9211 owns that boundary
and must stay green alongside this file.

Parallel-safe: rows are created under the fixture's unique test_tenant_key on a
TransactionalTestContext session; no module-level state.
"""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from giljo_mcp.exceptions import ProjectStateError
from giljo_mcp.models.auth import User
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.services.template_service import USER_MANAGED_AGENT_LIMIT


def _active_template(tenant_key: str, product_id: str, role: str) -> AgentTemplate:
    """A tenant-active template occupying one user-managed role slot."""
    return AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"be9394-slot-{role}",
        role=role,
        category="custom",
        system_instructions="slot seed",
        is_active=True,
    )


def _user(tenant_key: str) -> User:
    return User(
        id=str(uuid4()),
        tenant_key=tenant_key,
        username=f"caller_{uuid4().hex[:6]}",
        email=f"caller_{uuid4().hex[:6]}@example.com",
        password_hash="not-used",
        role="developer",
        is_active=True,
    )


async def _fill_to_cap(db_session, tenant_key: str, product_id: str, count: int) -> None:
    for i in range(count):
        db_session.add(_active_template(tenant_key, product_id, f"be9394-role-{i}"))
    await db_session.flush()


def _create_payload(**overrides):
    from api.endpoints.templates.models import TemplateCreate

    kwargs = {"role": f"be9394-new-{uuid4().hex[:6]}", "cli_tool": "claude", "is_active": True}
    kwargs.update(overrides)
    return TemplateCreate(**kwargs)


async def test_seventeenth_born_active_agent_is_refused(db_session, template_service, test_tenant_key, test_product):
    """THE BYPASS: at the cap, a born-ACTIVE create must be refused, not admitted.

    15 active user roles occupy every user-managed slot (the 16th is the reserved
    orchestrator). Creating a 16th distinct active role — the 17th total — is the
    request the update path has always rejected, and creation must reject it the
    same way.
    """
    await _fill_to_cap(db_session, test_tenant_key, test_product.id, USER_MANAGED_AGENT_LIMIT)

    with pytest.raises(ProjectStateError) as excinfo:
        await template_service.create_template_from_request(db_session, _create_payload(), test_tenant_key, "tester")

    # Same message contract the update path raises, so the UI can render one string.
    assert str(USER_MANAGED_AGENT_LIMIT) in str(excinfo.value.message)


async def test_the_create_endpoint_translates_the_refusal_to_409(
    db_session, template_service, test_tenant_key, test_product
):
    """The error CONTRACT, not just the raise.

    The create endpoint caught only ValidationError -> 400, so a ProjectStateError
    would have escaped as an unhandled 500. "The DB constraint will catch it" is
    banned for exactly this reason: a rejection must arrive as a 409 the client can
    act on, matching the update path.
    """
    from api.endpoints.templates.crud import create_template

    await _fill_to_cap(db_session, test_tenant_key, test_product.id, USER_MANAGED_AGENT_LIMIT)

    with pytest.raises(HTTPException) as excinfo:
        await create_template(
            template=_create_payload(),
            current_user=_user(test_tenant_key),
            session=db_session,
            template_service=template_service,
        )

    assert excinfo.value.status_code == 409
    assert str(USER_MANAGED_AGENT_LIMIT) in str(excinfo.value.detail)


async def test_the_sixteenth_total_slot_is_still_accepted(db_session, template_service, test_tenant_key, test_product):
    """Boundary, so the gate cannot pass by being off by one and refusing everything.

    14 active roles leaves one user-managed slot free; a born-active create must
    still succeed and land tenant-active.
    """
    await _fill_to_cap(db_session, test_tenant_key, test_product.id, USER_MANAGED_AGENT_LIMIT - 1)

    created = await template_service.create_template_from_request(
        db_session, _create_payload(), test_tenant_key, "tester"
    )

    assert created.is_active is True


async def test_a_born_inactive_agent_is_not_gated_at_the_cap(
    db_session, template_service, test_tenant_key, test_product
):
    """A template that is NOT born active consumes no slot, so the cap must ignore it.

    This is the half that keeps the gate honest: the limit counts ACTIVE roles, and
    gating creation outright would break the pre-BE-9391 flow (create inactive, then
    activate through the update gate) that BE-9211 still pins.
    """
    await _fill_to_cap(db_session, test_tenant_key, test_product.id, USER_MANAGED_AGENT_LIMIT)

    created = await template_service.create_template_from_request(
        db_session, _create_payload(is_active=False), test_tenant_key, "tester"
    )

    assert created.is_active is False
