# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest

from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.services.template_service import FACTORY_ORIGIN_TAG
from giljo_mcp.template_seeder import _get_default_templates_v103


FACTORY_TAGS = ["default", "product"]


def _default_def(role: str) -> dict:
    return next(t for t in _get_default_templates_v103() if t["role"] == role)


def _make_template(tenant_key: str, product_id: str, **overrides) -> AgentTemplate:
    fields = {
        "id": str(uuid4()),
        "tenant_key": tenant_key,
        "product_id": product_id,
        "name": "tester",
        "role": "tester",
        "category": "role",
        "cli_tool": "claude",
        "background_color": "#4A90D9",
        "description": "Seeded crew member",
        "system_instructions": "MCP bootstrap placeholder",
        "user_instructions": "Customized by the user",
        "model": "sonnet",
        "effort": "high",
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
@pytest.mark.parametrize(
    ("name", "role"),
    [("tester-2", "tester"), ("implementer-backend", "implementer")],
)
async def test_reset_of_suffixed_or_renamed_factory_agent_restores_its_role_default(
    db_session, template_service, test_tenant_key, test_product, name, role
):
    template = _make_template(test_tenant_key, test_product.id, name=name, role=role)
    db_session.add(template)
    await db_session.commit()

    await template_service.reset_template_to_defaults(db_session, template)

    assert template.user_instructions == _default_def(role)["user_instructions"]


@pytest.mark.asyncio
async def test_reset_of_plain_factory_agent_is_byte_identical_to_today(
    db_session, template_service, test_tenant_key, test_product
):
    template = _make_template(test_tenant_key, test_product.id, name="tester", role="tester")
    db_session.add(template)
    await db_session.commit()

    await template_service.reset_template_to_defaults(db_session, template)

    assert template.user_instructions == _default_def("tester")["user_instructions"]
    assert template.tags == ["default", "tenant"]
    assert template.behavioral_rules == []
    assert template.success_criteria == []


@pytest.mark.asyncio
async def test_reset_leaves_identity_and_wiring_fields_untouched(
    db_session, template_service, test_tenant_key, test_product
):
    template = _make_template(
        test_tenant_key,
        test_product.id,
        name="tester-3",
        role="tester",
        background_color="#123456",
        model="opus",
        effort="max",
        cli_tool="codex",
        description="My own words",
    )
    db_session.add(template)
    await db_session.commit()
    before = (
        template.name,
        template.role,
        template.background_color,
        template.cli_tool,
        template.model,
        template.effort,
        template.description,
        template.system_instructions,
        template.is_active,
        template.is_default,
        template.product_id,
    )

    await template_service.reset_template_to_defaults(db_session, template)

    assert before == (
        template.name,
        template.role,
        template.background_color,
        template.cli_tool,
        template.model,
        template.effort,
        template.description,
        template.system_instructions,
        template.is_active,
        template.is_default,
        template.product_id,
    )


@pytest.mark.asyncio
async def test_user_created_agent_has_no_factory_default_and_still_resets_blank(
    db_session, template_service, test_tenant_key, test_product
):
    template = _make_template(
        test_tenant_key,
        test_product.id,
        name="tester-specialist",
        role="tester",
        tags=[],
        created_by="someone",
    )
    db_session.add(template)
    await db_session.commit()

    await template_service.reset_template_to_defaults(db_session, template)

    assert template.user_instructions is None


@pytest.mark.asyncio
async def test_reset_never_strips_the_factory_origin_marker(
    db_session, template_service, test_tenant_key, test_product
):
    template = _make_template(test_tenant_key, test_product.id, name="tester-2", role="tester")
    db_session.add(template)
    await db_session.commit()

    await template_service.reset_template_to_defaults(db_session, template)
    assert FACTORY_ORIGIN_TAG in template.tags

    await template_service.reset_template_to_defaults(db_session, template)
    assert FACTORY_ORIGIN_TAG in template.tags
    assert template.user_instructions == _default_def("tester")["user_instructions"]


@pytest.mark.asyncio
async def test_agent_already_damaged_by_the_old_bug_is_recovered_without_a_migration(
    db_session, template_service, test_tenant_key, test_product
):
    damaged = _make_template(
        test_tenant_key,
        test_product.id,
        name="implementer-backend",
        role="implementer",
        tags=[],
        user_instructions=None,
    )
    db_session.add(damaged)
    await db_session.commit()

    await template_service.reset_template_to_defaults(db_session, damaged)

    assert damaged.user_instructions == _default_def("implementer")["user_instructions"]
    assert FACTORY_ORIGIN_TAG in damaged.tags
