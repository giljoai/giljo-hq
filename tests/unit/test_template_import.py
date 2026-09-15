# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentTemplate
from giljo_mcp.template_import import import_default_templates
from tests.helpers.product_crew_helper import make_product, seed_crew


pytestmark = pytest.mark.asyncio

DEFAULT_NAMES = {"implementer", "tester", "analyzer", "reviewer", "documenter"}


async def _enabled_names(db_session, tenant_key: str, product_id: str) -> set[str]:
    from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment

    with tenant_session_context(db_session, tenant_key):
        stmt = (
            select(AgentTemplate.name)
            .join(ProductAgentAssignment, ProductAgentAssignment.template_id == AgentTemplate.id)
            .where(
                ProductAgentAssignment.product_id == product_id,
                ProductAgentAssignment.tenant_key == tenant_key,
                ProductAgentAssignment.is_active.is_(True),
            )
        )
        return {row[0] for row in (await db_session.execute(stmt)).all()}


async def _fetch_templates(db_session, tenant_key: str) -> list[AgentTemplate]:
    with tenant_session_context(db_session, tenant_key):
        stmt = select(AgentTemplate).where(
            AgentTemplate.tenant_key == tenant_key,
            AgentTemplate.deleted_at.is_(None),
        )
        return list((await db_session.execute(stmt)).scalars().all())


async def test_fresh_tenant_imports_all_five_defaults(db_session):
    tenant_key = f"fe9203-fresh-{uuid4().hex[:8]}"
    product = await make_product(db_session, tenant_key)

    report = await import_default_templates(db_session, tenant_key, product.id)

    assert sorted(report.added) == sorted(DEFAULT_NAMES)
    assert report.added_as_duplicate == []
    assert report.skipped_identical == []

    templates = await _fetch_templates(db_session, tenant_key)
    assert {t.name for t in templates} == DEFAULT_NAMES
    for t in templates:
        assert t.is_active is True
        assert t.is_default is True
        assert t.tags == ["default", "product"]
        assert "orchestrator" not in t.name
        assert t.product_id == product.id, "imported agents belong to the product they were imported into"

    enabled = await _enabled_names(db_session, tenant_key, product.id)
    assert enabled == DEFAULT_NAMES


async def test_import_into_seeded_product_skips_everything(db_session):
    tenant_key = f"fe9203-seeded-{uuid4().hex[:8]}"
    product, _names = await seed_crew(db_session, tenant_key)

    report = await import_default_templates(db_session, tenant_key, product.id)

    assert report.added == []
    assert report.added_as_duplicate == []
    assert sorted(report.skipped_identical) == sorted(DEFAULT_NAMES)
    assert len(await _fetch_templates(db_session, tenant_key)) == 5


async def test_edited_default_gets_pristine_duplicate_and_stays_untouched(db_session):
    tenant_key = f"fe9203-edited-{uuid4().hex[:8]}"
    product, _names = await seed_crew(db_session, tenant_key)

    templates = await _fetch_templates(db_session, tenant_key)
    implementer = next(t for t in templates if t.name == "implementer")
    edited_prose = "MY CUSTOM IMPLEMENTER PROSE — do not clobber"
    implementer.user_instructions = edited_prose
    await db_session.commit()

    report = await import_default_templates(db_session, tenant_key, product.id)

    assert report.added_as_duplicate == ["implementer-duplicate"]
    assert report.added == []
    assert sorted(report.skipped_identical) == sorted(DEFAULT_NAMES - {"implementer"})

    templates = await _fetch_templates(db_session, tenant_key)
    by_name = {t.name: t for t in templates}
    assert by_name["implementer"].user_instructions == edited_prose
    duplicate = by_name["implementer-duplicate"]
    assert duplicate.is_default is False
    assert duplicate.role == "implementer"
    assert "do not clobber" not in (duplicate.user_instructions or "")


async def test_repeat_click_never_multiplies_duplicates(db_session):
    tenant_key = f"fe9203-repeat-{uuid4().hex[:8]}"
    product, _names = await seed_crew(db_session, tenant_key)

    templates = await _fetch_templates(db_session, tenant_key)
    implementer = next(t for t in templates if t.name == "implementer")
    implementer.user_instructions = "edited"
    await db_session.commit()

    first = await import_default_templates(db_session, tenant_key, product.id)
    second = await import_default_templates(db_session, tenant_key, product.id)
    third = await import_default_templates(db_session, tenant_key, product.id)

    assert first.added_as_duplicate == ["implementer-duplicate"]
    assert second.added_as_duplicate == []
    assert third.added_as_duplicate == []
    assert "implementer" in second.skipped_identical
    assert len(await _fetch_templates(db_session, tenant_key)) == 6


async def test_missing_default_is_recreated_without_stealing_default_flag(db_session):
    tenant_key = f"fe9203-flag-{uuid4().hex[:8]}"
    product = await make_product(db_session, tenant_key)

    with tenant_session_context(db_session, tenant_key):
        db_session.add(
            AgentTemplate(
                id=str(uuid4()),
                tenant_key=tenant_key,
                name="implementer-mine",
                product_id=product.id,
                category="role",
                role="implementer",
                system_instructions="x",
                user_instructions="my own implementer",
                is_active=True,
                is_default=True,
                version="1.0.0",
                created_at=datetime.now(UTC),
            )
        )
        await db_session.commit()

    report = await import_default_templates(db_session, tenant_key, product.id)

    assert "implementer" in report.added
    templates = await _fetch_templates(db_session, tenant_key)
    by_name = {t.name: t for t in templates}
    assert by_name["implementer"].is_default is False
    assert by_name["implementer-mine"].is_default is True
    assert by_name["implementer-mine"].user_instructions == "my own implementer"


async def test_two_tenant_isolation(db_session):
    tenant_a = f"fe9203-iso-a-{uuid4().hex[:8]}"
    tenant_b = f"fe9203-iso-b-{uuid4().hex[:8]}"
    product_a = await make_product(db_session, tenant_a)
    product_b = await make_product(db_session, tenant_b)

    report_a = await import_default_templates(db_session, tenant_a, product_a.id)

    assert len(report_a.added) == 5
    assert len(await _fetch_templates(db_session, tenant_a)) == 5
    assert await _fetch_templates(db_session, tenant_b) == []

    report_b = await import_default_templates(db_session, tenant_b, product_b.id)
    assert len(report_b.added) == 5
    assert len(await _fetch_templates(db_session, tenant_a)) == 5
    assert len(await _fetch_templates(db_session, tenant_b)) == 5


async def test_empty_tenant_key_rejected(db_session):
    with pytest.raises(ValueError):
        await import_default_templates(db_session, "", "some-product")


async def test_empty_product_id_rejected(db_session):
    with pytest.raises(ValueError):
        await import_default_templates(db_session, f"fe9203-noproduct-{uuid4().hex[:8]}", "")


async def test_a_second_product_imports_its_own_copies(db_session):
    tenant_key = f"fe9203-second-{uuid4().hex[:8]}"
    await seed_crew(db_session, tenant_key)
    second = await make_product(db_session, tenant_key, name="Second product")

    report = await import_default_templates(db_session, tenant_key, second.id)

    assert len(report.added) + len(report.added_as_duplicate) == 5, (
        f"the second product must get its own five agents; got {report}"
    )
    owned = [t for t in await _fetch_templates(db_session, tenant_key) if t.product_id == second.id]
    assert len(owned) == 5
    assert {t.name for t in owned}.isdisjoint(DEFAULT_NAMES)
