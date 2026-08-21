# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9337 -- a trashed agent template must drop out of the spawn ALLOWLIST.

The seventh site of the BE-9325 defect, in the same repository file.
``AgentCompletionRepository.get_active_template_names``
(``agent_completion_repository.py:465-487``) filters ``tenant_key + is_active``
and never looks at ``deleted_at``. Soft-delete stamps ``deleted_at`` and
deliberately leaves ``is_active`` True (``template_service.py:720``), so every
deleted template stays on that list.

That list is the validation allowlist in ``JobLifecycleService``
(``job_lifecycle_service.py:535-543``): the set of names a spawn is accepted
against, and the set a rejected spawn is told to choose from. The templates API
correctly hides trashed rows, so two surfaces disagree about which agents exist
and the one that disagrees is the one that gates spawning.

These are REAL-DATABASE tests on purpose. The defect is in the WHERE clause; a
mocked result cannot see it, because a mock returns whatever it was told to
return regardless of what the SQL actually selects. Same reasoning, and same
fixture shape, as ``tests/services/test_be9325_trashed_template_lifecycle.py``.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.projects import Project
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.agent_completion_repository import AgentCompletionRepository
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService


def _template(tenant_key: str, name: str, *, deleted: bool = False) -> AgentTemplate:
    """A minimally-valid active template row, optionally already trashed.

    ``is_active=True`` on a trashed row is not a contrivance for the test -- it
    is exactly what soft-delete leaves behind, and it is the whole bug.
    """
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
    """The failing layer: the repository query that builds the allowlist.

    The user deleted this agent. The templates API stopped showing it. This
    query still hands its name to the spawn validator as a live choice.
    """
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
    """Regression guard against an over-broad filter.

    Cheap, and it is the assertion that catches a "fix" that empties the list --
    which would pass every other test in this file.
    """
    live_name = f"be9337-live-{uuid4().hex[:8]}"
    db_session.add(_template(test_tenant_key, live_name))
    await db_session.flush()

    names = await AgentCompletionRepository().get_active_template_names(db_session, test_tenant_key)

    assert live_name in names, "A live template must still be a valid spawn target."


@pytest.mark.asyncio
async def test_inactive_template_stays_off_the_list(db_session, test_tenant_key):
    """The pre-existing ``is_active`` filter must survive the fix.

    ``deleted_at IS NULL`` is an ADDITIONAL predicate, not a replacement -- a
    deactivated-but-not-deleted template was never a valid spawn target and
    must not become one.
    """
    inactive_name = f"be9337-inactive-{uuid4().hex[:8]}"
    inactive = _template(test_tenant_key, inactive_name)
    inactive.is_active = False
    db_session.add(inactive)
    await db_session.flush()

    names = await AgentCompletionRepository().get_active_template_names(db_session, test_tenant_key)

    assert inactive_name not in names, "A deactivated template must not be a valid spawn target."


@pytest.mark.asyncio
async def test_spawn_rejection_message_does_not_offer_a_deleted_agent(
    db_session, db_manager, tenant_manager, test_tenant_key, test_project_id
):
    """The user-visible surface: what a rejected spawn is told to choose from.

    ``_validate_spawn_agent`` renders the allowlist verbatim into the
    ValidationError ("Must be one of: [...]") and into ``context['valid_names']``.
    Before the fix that list names deleted agents, so the remedy the error
    recommends includes choices that resolve to nothing.
    """
    deleted_name = f"be9337-msg-deleted-{uuid4().hex[:8]}"
    live_name = f"be9337-msg-live-{uuid4().hex[:8]}"
    db_session.add_all(
        [
            _template(test_tenant_key, deleted_name, deleted=True),
            _template(test_tenant_key, live_name),
        ]
    )
    await db_session.flush()

    service = JobLifecycleService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )

    # BE-9385a: _validate_spawn_agent takes the project (it reads product_id off it
    # to scope the allowlist), so load the real row rather than passing a bare id.
    project = (await db_session.execute(select(Project).where(Project.id == test_project_id))).scalar_one()

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
