# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models import Product, Project, Task
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.repositories.product_memory_repository import ProductMemoryRepository
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.services.dto import MemoryEntryCreateParams
from giljo_mcp.services.task_service._mcp_read_layer import apply_task_filters
from giljo_mcp.tenant import TenantManager


_PROJECT_REPO = ProjectRepository()

_TOKEN = "cerulean-hallway-92"




@pytest_asyncio.fixture
async def matched_pair_seed(db_session):
    tenant = TenantManager.generate_tenant_key()
    product = Product(
        id=str(uuid.uuid4()),
        name="BE-9469 search field product",
        description="seed",
        tenant_key=tenant,
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()

    be_type = TaxonomyType(id=str(uuid.uuid4()), tenant_key=tenant, abbreviation="BE", label="Backend")
    db_session.add(be_type)
    await db_session.commit()

    project = Project(
        id=str(uuid.uuid4()),
        name="Wombat tracker",
        description=f"Rewrote the onboarding flow -- {_TOKEN} -- fixed the redirect bug.",
        mission="m",
        alias="ZQ9K7M",
        tenant_key=tenant,
        product_id=product.id,
        status="inactive",
        project_type_id=be_type.id,
        series_number=9101,
    )
    db_session.add(project)

    task = Task(
        id=str(uuid.uuid4()),
        title="Wombat companion task",
        description=f"Same fix, tracked separately -- {_TOKEN} -- ",
        tenant_key=tenant,
        product_id=product.id,
        status="pending",
        priority="medium",
    )
    db_session.add(task)
    await db_session.commit()

    return {"tenant": tenant, "product": product, "project": project, "task": task}


class TestMatchedPairSearchFieldGap:

    @pytest.mark.asyncio
    async def test_task_query_finds_the_token_in_description(self, db_session, matched_pair_seed):
        tenant = matched_pair_seed["tenant"]
        stmt = apply_task_filters(
            select(Task).where(Task.tenant_key == tenant),
            status=None,
            priority=None,
            task_type_id=None,
            hidden=None,
            query=_TOKEN,
        )
        result = await db_session.execute(stmt)
        rows = result.scalars().all()
        assert {r.title for r in rows} == {"Wombat companion task"}, (
            f"control: list_tasks query={_TOKEN!r} matched {[r.title for r in rows]} -- expected "
            "the task to be found by its description (already shipped behavior)"
        )

    @pytest.mark.asyncio
    async def test_project_query_finds_the_same_token_in_description(self, db_session, matched_pair_seed):
        tenant = matched_pair_seed["tenant"]
        product = matched_pair_seed["product"]

        rows = await _PROJECT_REPO.list_projects(db_session, tenant, product_id=product.id, search=_TOKEN)

        assert {r.name for r in rows} == {"Wombat tracker"}, (
            f"list_projects(query={_TOKEN!r}) matched {[r.name for r in rows]} of 1 expected -- "
            "description is not in the projects search OR-clause (U8-F1)"
        )

    @pytest.mark.asyncio
    async def test_project_query_finds_by_project_alias(self, db_session, matched_pair_seed):
        tenant = matched_pair_seed["tenant"]
        product = matched_pair_seed["product"]

        rows = await _PROJECT_REPO.list_projects(db_session, tenant, product_id=product.id, search="ZQ9K7M")

        assert {r.name for r in rows} == {"Wombat tracker"}, (
            "list_projects(query='ZQ9K7M') did not find the project by its project_alias (U8-F2)"
        )




@pytest_asyncio.fixture
async def wildcard_probe_new_fields(db_session):
    tenant = TenantManager.generate_tenant_key()
    product = Product(
        id=str(uuid.uuid4()),
        name="BE-9469 escaping guard product",
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
            name="Percent in description",
            description="progress shown as 50% funded",
            alias="ALIAS1",
            mission="m",
            tenant_key=tenant,
            product_id=product.id,
            status="inactive",
            project_type_id=be_type.id,
            series_number=9301,
        ),
        Project(
            id=str(uuid.uuid4()),
            name="Underscore in description",
            description="snake_case_variable_name used here",
            alias="ALIAS2",
            mission="m",
            tenant_key=tenant,
            product_id=product.id,
            status="inactive",
            project_type_id=be_type.id,
            series_number=9302,
        ),
        Project(
            id=str(uuid.uuid4()),
            name="Percent in alias",
            description="ordinary description",
            alias="A%B123",
            mission="m",
            tenant_key=tenant,
            product_id=product.id,
            status="inactive",
            project_type_id=be_type.id,
            series_number=9303,
        ),
        Project(
            id=str(uuid.uuid4()),
            name="Underscore in alias",
            description="ordinary description",
            alias="C_D456",
            mission="m",
            tenant_key=tenant,
            product_id=product.id,
            status="inactive",
            project_type_id=be_type.id,
            series_number=9304,
        ),
        Project(
            id=str(uuid.uuid4()),
            name="Plain control",
            description="nothing special here",
            alias="PLAIN1",
            mission="m",
            tenant_key=tenant,
            product_id=product.id,
            status="inactive",
            project_type_id=be_type.id,
            series_number=9305,
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    return {"tenant": tenant, "product": product}


class TestEscapingGuardOnNewFields:

    @pytest.mark.asyncio
    async def test_bare_percent_matches_only_the_literal_percent_rows(self, db_session, wildcard_probe_new_fields):
        tenant = wildcard_probe_new_fields["tenant"]
        product = wildcard_probe_new_fields["product"]

        rows = await _PROJECT_REPO.list_projects(db_session, tenant, product_id=product.id, search="%")

        assert {r.name for r in rows} == {"Percent in description", "Percent in alias"}, (
            f"search='%' matched {[r.name for r in rows]} -- expected only the two rows with a "
            "literal '%' in description/alias; '%' is being consumed as a live SQL wildcard"
        )

    @pytest.mark.asyncio
    async def test_bare_underscore_matches_only_the_literal_underscore_rows(
        self, db_session, wildcard_probe_new_fields
    ):
        tenant = wildcard_probe_new_fields["tenant"]
        product = wildcard_probe_new_fields["product"]

        rows = await _PROJECT_REPO.list_projects(db_session, tenant, product_id=product.id, search="_")

        assert {r.name for r in rows} == {"Underscore in description", "Underscore in alias"}, (
            f"search='_' matched {[r.name for r in rows]} -- expected only the two rows with a "
            "literal '_' in description/alias; '_' is being consumed as a live SQL single-char wildcard"
        )

    @pytest.mark.asyncio
    async def test_ordinary_description_word_still_matches(self, db_session, wildcard_probe_new_fields):
        tenant = wildcard_probe_new_fields["tenant"]
        product = wildcard_probe_new_fields["product"]

        rows = await _PROJECT_REPO.list_projects(db_session, tenant, product_id=product.id, search="funded")

        assert {r.name for r in rows} == {"Percent in description"}

    @pytest.mark.asyncio
    async def test_ordinary_alias_still_matches(self, db_session, wildcard_probe_new_fields):
        tenant = wildcard_probe_new_fields["tenant"]
        product = wildcard_probe_new_fields["product"]

        rows = await _PROJECT_REPO.list_projects(db_session, tenant, product_id=product.id, search="PLAIN1")

        assert {r.name for r in rows} == {"Plain control"}




class TestSearchMemoryReachesCommitMessages:

    @pytest.mark.asyncio
    async def test_commit_message_found_via_the_fts_path(self, db_session, test_product, test_tenant_key):
        repo = ProductMemoryRepository()
        distinctive_message = "repaired the quantumwidget redirect handler"

        await repo.create_entry(
            session=db_session,
            params=MemoryEntryCreateParams(
                tenant_key=test_tenant_key,
                product_id=test_product.id,
                sequence=9001,
                entry_type="project_completion",
                source="test_be9469",
                timestamp=datetime.now(tz=UTC),
                summary="Unrelated summary text -- shipped the read layer.",
                git_commits=[{"sha": "abc1234", "message": distinctive_message, "author": "test"}],
            ),
        )

        entries, _ = await repo.get_memory_entries_paginated(
            session=db_session,
            product_id=test_product.id,
            tenant_key=test_tenant_key,
            search_query="quantumwidget redirect",
        )

        assert [e.sequence for e in entries] == [9001], (
            "search_memory did not find the commit message via the FTS path -- "
            "_FTS_DOCUMENT_SQL is missing git_commits (BE-9469 deliverable 3)"
        )

    @pytest.mark.asyncio
    async def test_commit_message_found_via_the_ilike_fallback_path(self, db_session, test_product, test_tenant_key):
        repo = ProductMemoryRepository()
        distinctive_message = "repaired the quantumwidget redirect handler"

        await repo.create_entry(
            session=db_session,
            params=MemoryEntryCreateParams(
                tenant_key=test_tenant_key,
                product_id=test_product.id,
                sequence=9002,
                entry_type="project_completion",
                source="test_be9469",
                timestamp=datetime.now(tz=UTC),
                summary="Unrelated summary text -- shipped the read layer.",
                git_commits=[{"sha": "def5678", "message": distinctive_message, "author": "test"}],
            ),
        )

        entries, _ = await repo.get_memory_entries_paginated(
            session=db_session,
            product_id=test_product.id,
            tenant_key=test_tenant_key,
            search_query="quantumwid",
        )

        assert [e.sequence for e in entries] == [9002], (
            "search_memory did not find the commit message via the ILIKE fallback path -- "
            "_ilike_stmt is missing git_commits (BE-9469 deliverable 3)"
        )
