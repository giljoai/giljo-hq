# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from uuid import uuid4

import pytest

from api.endpoints.templates.crud import _convert_to_response
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.services.template_service import differs_from_builtin
from giljo_mcp.template_seeder import _get_default_templates_v103, _seeded_user_instructions


FACTORY_TAGS = ["default", "product"]
_PREVIOUS_GENERATION_IMPLEMENTER = (
    "You are an implementation specialist responsible for writing clean, production-grade code.\n\n"
    "Your primary responsibilities:\n- Implement features according to specifications\n"
    "- Follow project coding standards and best practices\n- Write self-documenting code with clear comments\n"
    "- Ensure cross-platform compatibility (Windows, macOS, Linux)\n- Handle errors gracefully with proper logging\n\n"
    "Key principles:\n- Write code for humans first, machines second\n- Prefer existing patterns over novel solutions\n"
    "- Never hardcode paths or credentials\n- Use pathlib for all file operations\n"
    "- Test edge cases and error conditions\n\n"
    "Success criteria:\n- Code passes all linting checks (Ruff, Black)\n- Implementation matches specification exactly\n"
    "- No breaking changes to existing functionality\n- Proper error handling and logging in place\n"
)


def _default_def(role: str) -> dict:
    return next(t for t in _get_default_templates_v103() if t["role"] == role)


def _make_template(tenant_key: str, product_id: str, **overrides) -> AgentTemplate:
    fields = {
        "id": str(uuid4()),
        "tenant_key": tenant_key,
        "product_id": product_id,
        "name": "implementer",
        "role": "implementer",
        "category": "role",
        "cli_tool": "claude",
        "background_color": "#3498DB",
        "description": "Seeded crew member",
        "system_instructions": "MCP bootstrap placeholder",
        "user_instructions": _seeded_user_instructions(_default_def("implementer")),
        "model": "sonnet",
        "effort": "inherit",
        "behavioral_rules": [],
        "success_criteria": [],
        "tags": list(FACTORY_TAGS),
        "is_active": True,
        "is_default": False,
        "version": "1.0.0",
    }
    fields.update(overrides)
    return AgentTemplate(**fields)


@pytest.mark.asyncio
async def test_stale_factory_copy_differs_from_builtin(db_session, test_tenant_key, test_product):
    template = _make_template(
        test_tenant_key, test_product.id, user_instructions=_PREVIOUS_GENERATION_IMPLEMENTER, updated_at=None
    )
    db_session.add(template)
    await db_session.commit()

    assert template.updated_at is None
    assert differs_from_builtin(template) is True


@pytest.mark.asyncio
async def test_edited_factory_row_differs_from_builtin(db_session, test_tenant_key, test_product):
    template = _make_template(
        test_tenant_key,
        test_product.id,
        name="implementer-backend",
        user_instructions="Our house implementer. Follow the style guide.",
        updated_at=datetime.now(UTC),
    )
    db_session.add(template)
    await db_session.commit()

    assert template.updated_at is not None
    assert differs_from_builtin(template) is True


@pytest.mark.asyncio
async def test_current_factory_copy_does_not_differ(db_session, test_tenant_key, test_product):
    template = _make_template(test_tenant_key, test_product.id, name="implementer-2")
    db_session.add(template)
    await db_session.commit()

    assert differs_from_builtin(template) is False


@pytest.mark.asyncio
async def test_user_made_agent_has_no_builtin_to_differ_from(db_session, test_tenant_key, test_product):
    template = _make_template(
        test_tenant_key,
        test_product.id,
        name="implementer-specialist",
        user_instructions="My own agent, my own words.",
        tags=[],
        created_by="someone",
    )
    db_session.add(template)
    await db_session.commit()

    assert differs_from_builtin(template) is None


@pytest.mark.asyncio
async def test_roster_response_carries_differs_from_builtin_beside_can_reset(db_session, test_tenant_key, test_product):
    stale = _make_template(test_tenant_key, test_product.id, user_instructions=_PREVIOUS_GENERATION_IMPLEMENTER)
    custom = _make_template(
        test_tenant_key, test_product.id, name="mine", user_instructions="Mine.", tags=[], created_by="me"
    )
    db_session.add_all([stale, custom])
    await db_session.commit()

    stale_row = _convert_to_response(stale)
    custom_row = _convert_to_response(custom)

    assert (stale_row.can_reset, stale_row.differs_from_builtin) == (True, True)
    assert (custom_row.can_reset, custom_row.differs_from_builtin) == (False, None)


@pytest.mark.asyncio
async def test_reset_restamps_version_from_the_definition(db_session, template_service, test_tenant_key, test_product):
    template = _make_template(
        test_tenant_key,
        test_product.id,
        name="implementer-2",
        user_instructions=_PREVIOUS_GENERATION_IMPLEMENTER,
        version="1.0.0",
    )
    db_session.add(template)
    await db_session.commit()
    assert _default_def("implementer")["version"] != "1.0.0", "fixture must start on an older version"

    await template_service.reset_template_to_defaults(db_session, template)

    assert template.version == _default_def("implementer")["version"]
    assert differs_from_builtin(template) is False


@pytest.mark.asyncio
async def test_reset_of_an_edited_row_clears_updated_at_so_the_next_seed_change_is_seen(
    db_session, template_service, test_tenant_key, test_product
):
    template = _make_template(
        test_tenant_key,
        test_product.id,
        name="implementer-2",
        user_instructions="Our house implementer. Edited by hand.",
        updated_at=datetime.now(UTC),
    )
    db_session.add(template)
    await db_session.commit()
    assert template.updated_at is not None
    assert differs_from_builtin(template) is True

    await template_service.reset_template_to_defaults(db_session, template)
    await template_service.commit_and_refresh_template(db_session, template)
    db_session.expire(template)
    await db_session.refresh(template)

    assert template.updated_at is None, "onupdate must not overwrite the explicit NULL"
    assert differs_from_builtin(template) is False

    template.user_instructions = _PREVIOUS_GENERATION_IMPLEMENTER
    await db_session.commit()
    await db_session.refresh(template)
    assert differs_from_builtin(template) is True


@pytest.mark.asyncio
async def test_reset_of_a_never_edited_stale_copy_keeps_updated_at_null(
    db_session, template_service, test_tenant_key, test_product
):
    template = _make_template(
        test_tenant_key, test_product.id, user_instructions=_PREVIOUS_GENERATION_IMPLEMENTER, updated_at=None
    )
    db_session.add(template)
    await db_session.commit()

    await template_service.reset_template_to_defaults(db_session, template)
    await template_service.commit_and_refresh_template(db_session, template)
    db_session.expire(template)
    await db_session.refresh(template)

    assert template.updated_at is None
    assert differs_from_builtin(template) is False
