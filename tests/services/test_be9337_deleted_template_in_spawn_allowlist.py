# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.projects import Project
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.agent_completion_repository import AgentCompletionRepository
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService
from tests.helpers.product_crew_helper import adopt_all_templates


def _template(tenant_key: str, name: str, *, deleted: bool = False) -> AgentTemplate:
    return AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=name,
        category="custom",
        system_instructions="sys",
        user_instructions="user",
        tool="claude",
        cli_tool="claude",
        is_active=True,
        deleted_at=datetime.now(UTC) if deleted else None,
    )


@pytest.mark.asyncio
async def test_deleted_template_is_not_in_the_active_name_list(db_session, test_tenant_key):
    deleted_name = f"be9337-deleted-{uuid4().hex[:8]}"
    db_session.add(_template(test_tenant_key, deleted_name, deleted=True))
    await db_session.flush()

    names = await AgentCompletionRepository().get_active_template_names(db_session, test_tenant_key)

    assert deleted_name not in names, (
        f"A soft-deleted template is still on the spawn allowlist ({deleted_name!r} in {names!r}). "
        "The user deleted this agent and the templates list no longer shows it, but a spawn "
        "against it is still accepted -- and binds no identity."
    )


@pytest.mark.asyncio
async def test_live_template_is_still_in_the_active_name_list(db_session, test_tenant_key):
    live_name = f"be9337-live-{uuid4().hex[:8]}"
    db_session.add(_template(test_tenant_key, live_name))
    await db_session.flush()

    names = await AgentCompletionRepository().get_active_template_names(db_session, test_tenant_key)

    assert live_name in names, "A live template must still be a valid spawn target."


@pytest.mark.asyncio
async def test_the_product_switch_is_what_keeps_an_agent_off_the_list(db_session, test_tenant_key, test_product):
    from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment

    off_name = f"be9337-off-{uuid4().hex[:8]}"
    on_name = f"be9337-on-{uuid4().hex[:8]}"
    switched_off = _template(test_tenant_key, off_name)
    switched_on = _template(test_tenant_key, on_name)
    switched_off.product_id = test_product.id
    switched_on.product_id = test_product.id
    db_session.add_all([switched_off, switched_on])
    db_session.add_all(
        [
            ProductAgentAssignment(
                id=str(uuid4()),
                product_id=test_product.id,
                template_id=switched_off.id,
                tenant_key=test_tenant_key,
                is_active=False,
            ),
            ProductAgentAssignment(
                id=str(uuid4()),
                product_id=test_product.id,
                template_id=switched_on.id,
                tenant_key=test_tenant_key,
                is_active=True,
            ),
        ]
    )
    await db_session.flush()

    names = await AgentCompletionRepository().get_active_template_names(
        db_session, test_tenant_key, product_id=test_product.id
    )

    assert off_name not in names, "An agent switched OFF for this product must not be a valid spawn target."
    assert on_name in names, "...and the one switched ON must still be."


@pytest.mark.asyncio
async def test_spawn_rejection_message_does_not_offer_a_deleted_agent(
    db_session, db_manager, tenant_manager, test_tenant_key, test_project_id
):
    deleted_name = f"be9337-msg-deleted-{uuid4().hex[:8]}"
    live_name = f"be9337-msg-live-{uuid4().hex[:8]}"
    db_session.add_all(
        [
            _template(test_tenant_key, deleted_name, deleted=True),
            _template(test_tenant_key, live_name),
        ]
    )
    await db_session.flush()

    project = (await db_session.execute(select(Project).where(Project.id == test_project_id))).scalar_one()
    await adopt_all_templates(db_session, test_tenant_key, project.product_id)

    service = JobLifecycleService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )

    with pytest.raises(ValidationError) as exc_info:
        await service._validate_spawn_agent(
            session=db_session,
            agent_display_name="implementer",
            agent_name=f"be9337-nonexistent-{uuid4().hex[:8]}",
            tenant_key=test_tenant_key,
            project=project,
            parent_job_id=None,
        )

    message = str(exc_info.value)
    valid_names = exc_info.value.context["valid_names"]

    assert deleted_name not in valid_names, (
        f"The spawn rejection offers a DELETED agent as a valid choice: {deleted_name!r} in "
        f"{valid_names!r}. The user is being told to pick an agent that no longer exists."
    )
    assert deleted_name not in message, "The rejection message text still names a deleted agent."
    assert live_name in valid_names, "The rejection must still offer the agents that do exist."
