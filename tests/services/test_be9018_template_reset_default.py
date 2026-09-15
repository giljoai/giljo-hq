# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.template_seeder import _get_default_templates_v103


@pytest.mark.asyncio
async def test_reset_default_named_template_restores_shipped_default(
    db_session, template_service, test_tenant_key, test_product
):
    from api.endpoints.templates.history import reset_template
    from giljo_mcp.models.auth import User

    default_def = next(t for t in _get_default_templates_v103() if t["name"] == "analyzer")
    assert default_def["user_instructions"]

    template = AgentTemplate(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        name="analyzer",
        role="analyzer",
        category="role",
        cli_tool="claude",
        system_instructions="MCP bootstrap placeholder",
        user_instructions="",
        behavioral_rules=[],
        success_criteria=[],
        tags=[],
        is_active=True,
        is_default=True,
        version="1.0.0",
    )
    db_session.add(template)
    await db_session.commit()

    caller = User(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        username=f"caller_{uuid4().hex[:6]}",
        email=f"caller_{uuid4().hex[:6]}@example.com",
        password_hash="not-used",
        role="developer",
        is_active=True,
    )

    response = await reset_template(
        template_id=template.id,
        current_user=caller,
        session=db_session,
        template_service=template_service,
    )

    assert response.user_instructions == default_def["user_instructions"]
    assert response.user_instructions.strip() != ""


@pytest.mark.asyncio
async def test_reset_custom_named_template_still_resets_blank(db_session, template_service, sample_template):
    sample_template.user_instructions = "Custom instructions"
    await db_session.commit()

    await template_service.reset_template_to_defaults(db_session, sample_template)

    assert sample_template.user_instructions is None


@pytest.mark.asyncio
async def test_spawn_time_identity_nonempty_after_reset_of_default_template(
    db_session, template_service, test_tenant_key, test_product
):
    from giljo_mcp.services.mission_service import MissionService

    default_def = next(t for t in _get_default_templates_v103() if t["name"] == "reviewer")

    template = AgentTemplate(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        name="reviewer",
        role="reviewer",
        category="role",
        cli_tool="claude",
        system_instructions="MCP bootstrap placeholder",
        user_instructions="",
        behavioral_rules=[],
        success_criteria=[],
        tags=[],
        is_active=True,
        is_default=True,
        version="1.0.0",
    )
    db_session.add(template)
    await db_session.commit()

    await template_service.reset_template_to_defaults(db_session, template)
    await db_session.commit()
    await db_session.refresh(template)

    svc = MissionService.__new__(MissionService)
    svc._logger = logging.getLogger("test_be9018")
    svc.db_manager = MagicMock()
    svc._repo = MagicMock()
    svc._repo.get_template_by_id = AsyncMock(return_value=template)

    job = SimpleNamespace(job_type="implementer", template_id=template.id, project_id=None, job_id="job-be9018")
    execution = SimpleNamespace(agent_name="reviewer", agent_display_name="reviewer")

    identity, identity_status, _source, _template = await svc._resolve_mission_template(
        MagicMock(), job, execution, test_tenant_key
    )

    assert identity is not None
    assert identity_status == "resolved"
    assert default_def["user_instructions"] in identity
