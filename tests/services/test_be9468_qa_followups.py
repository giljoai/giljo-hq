# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Product, Project
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.tenant import TenantManager


_REPO = ProjectRepository()




@pytest_asyncio.fixture
async def wildcard_probe_projects(db_session):
    tenant = TenantManager.generate_tenant_key()
    product = Product(
        id=str(uuid.uuid4()),
        name="BE-9468 QA followups product",
        description="seed",
        tenant_key=tenant,
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()

    be_type = TaxonomyType(id=str(uuid.uuid4()), tenant_key=tenant, abbreviation="BE", label="Backend")
    db_session.add(be_type)
    await db_session.commit()

    rows = [
        Project(
            id=str(uuid.uuid4()),
            name=name,
            description="d",
            mission="m",
            tenant_key=tenant,
            product_id=product.id,
            status="inactive",
            project_type_id=be_type.id,
            series_number=series,
        )
        for name, series in [
            ("OAuth handler", 9001),
            ("Alpha widget", 9002),
            ("Bravo widget", 9003),
        ]
    ]
    db_session.add_all(rows)
    await db_session.commit()

    return {"tenant": tenant, "product": product, "rows": rows}


class TestSearchDoesNotTreatLikeMetacharactersAsWildcards:

    @pytest.mark.asyncio
    async def test_bare_percent_does_not_match_the_whole_board(self, db_session, wildcard_probe_projects):
        tenant = wildcard_probe_projects["tenant"]
        product = wildcard_probe_projects["product"]

        rows = await _REPO.list_projects(db_session, tenant, product_id=product.id, search="%")

        assert rows == [], (
            f"search='%' matched {len(rows)} of 3 seeded projects -- '%' is being "
            "consumed as a live SQL wildcard instead of a literal character"
        )

    @pytest.mark.asyncio
    async def test_bare_underscore_does_not_match_the_whole_board(self, db_session, wildcard_probe_projects):
        tenant = wildcard_probe_projects["tenant"]
        product = wildcard_probe_projects["product"]

        rows = await _REPO.list_projects(db_session, tenant, product_id=product.id, search="_")

        assert rows == [], (
            f"search='_' matched {len(rows)} of 3 seeded projects -- '_' is being "
            "consumed as a live SQL single-char wildcard instead of a literal character"
        )

    @pytest.mark.asyncio
    async def test_percent_wrapped_query_differs_from_the_bare_word(self, db_session, wildcard_probe_projects):
        tenant = wildcard_probe_projects["tenant"]
        product = wildcard_probe_projects["product"]

        bare = await _REPO.list_projects(db_session, tenant, product_id=product.id, search="oauth")
        wrapped = await _REPO.list_projects(db_session, tenant, product_id=product.id, search="%oauth%")

        assert {r.name for r in bare} == {"OAuth handler"}
        assert wrapped == [], (
            f"search='%oauth%' matched {len(wrapped)} rows, same as bare 'oauth' "
            "(byte-identical result) -- the '%' are being consumed as wildcards"
        )

    @pytest.mark.asyncio
    async def test_count_projects_agrees_with_list_projects_on_the_escaped_search(
        self, db_session, wildcard_probe_projects
    ):
        tenant = wildcard_probe_projects["tenant"]
        product = wildcard_probe_projects["product"]

        total = await _REPO.count_projects(db_session, tenant, product_id=product.id, search="%")
        rows = await _REPO.list_projects(db_session, tenant, product_id=product.id, search="%")

        assert total == len(rows) == 0

    @pytest.mark.asyncio
    async def test_both_sides_guard_a_real_word_still_matches(self, db_session, wildcard_probe_projects):
        tenant = wildcard_probe_projects["tenant"]
        product = wildcard_probe_projects["product"]

        rows = await _REPO.list_projects(db_session, tenant, product_id=product.id, search="widget")

        assert {r.name for r in rows} == {"Alpha widget", "Bravo widget"}




class TestListTasksLimitZeroUsesTheDefault:
    @pytest.mark.asyncio
    async def test_limit_zero_returns_the_default_page_instead_of_raising(self, db_session, two_tenant_service_setup):
        tenant_a = two_tenant_service_setup["tenant_a"]
        db_manager = two_tenant_service_setup["db_manager"]
        task_service_a = two_tenant_service_setup["task_service_a"]

        await task_service_a.create_task_for_mcp(
            title="BE-9468 followups probe task",
            description="",
            tenant_key=tenant_a,
            db_manager=db_manager,
        )

        response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, limit=0)

        assert response["count"] == 1
        assert response["tasks"][0]["title"] == "BE-9468 followups probe task"

    @pytest.mark.asyncio
    async def test_negative_limit_is_still_rejected(self, db_session, two_tenant_service_setup):
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]

        with pytest.raises(ValidationError):
            await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, limit=-1)
