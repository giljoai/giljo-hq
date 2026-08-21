# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9469 item 3 -- search covers what users actually say.

Black-box QA on the 471-project board (2026-08-19, U8-F1/U8-F2) proved by matched
pair: ``list_tasks`` ``query`` searches title + description + taxonomy_alias;
``list_projects`` ``query`` searches name + id + taxonomy_alias only -- NOT
``description``, NOT ``project_alias`` (the 6-char ``Project.alias`` code, e.g.
``QWL2H8``). The operator's own scenario -- "find the completed project that
changed the UI to blue" -- fails on projects when the phrase lives in the
description, and works on tasks. The asymmetry is the defect.

This module has three parts:

1. The matched-pair RED (``TestMatchedPairSearchFieldGap``) -- same token, same
   shape, task side already finds it (control), project side does not (the bug).
   Reproduces at the repository layer, the layer ``_build_list_conditions``
   actually lives at.
2. The escaping guard on the two NEW fields (``TestEscapingGuardOnNewFields``) --
   ``%``/``_`` must stay literal on ``description`` and ``alias``, same as the
   shipped guard already proves for ``name``/``id``/``taxonomy_alias``
   (``aa249c979``).
3. Deliverable 3 (``TestSearchMemoryReachesCommitMessages``): whether
   ``search_memory`` reaches the git commit messages stored in closeouts.
   MEASURED FIRST (RED, 2026-08-19): neither the FTS document nor the ILIKE
   fallback in ``ProductMemoryRepository`` included ``git_commits`` -- a
   distinctive commit message was NOT findable. Per the brief's standing
   pre-ruling #4 this was verify-then-propose, never build-first; the gap and
   a proposed smallest fix were measured and reviewed under the BE-9469
   project ruling, approved to build (both the FTS document AND the ILIKE
   fallback, plus a migration to keep ``idx_pme_fts`` in sync -- see
   ``migrations/versions/ce_0096_pme_fts_git_commits_be9469.py`` and
   ``test_be9469_pme_fts_git_commits_parity.py``). This class now asserts the
   fix: a commit message is reachable via BOTH match paths independently
   (constraint 2 -- "both paths or neither").

Edition Scope: Both.
"""

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

# A token that appears in NEITHER project name/id/taxonomy_alias NOR any other
# seeded row -- the only way it can be found is via the description field.
_TOKEN = "cerulean-hallway-92"


# ---------------------------------------------------------------------------
# Part 1 -- the matched-pair RED: description search gap on list_projects
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def matched_pair_seed(db_session):
    """One project and one task, same distinctive token in ``description``,
    the project also carrying a fixed ``alias`` so the alias-search gap can be
    proven in the same fixture."""
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
    """U8-F1/U8-F2 reproduced live: same token, task side finds it, project side does not."""

    @pytest.mark.asyncio
    async def test_task_query_finds_the_token_in_description(self, db_session, matched_pair_seed):
        """CONTROL: list_tasks' query already searches description (shipped, correct).
        If this ever goes red, suspect the harness/fixture, not the project-side fix."""
        tenant = matched_pair_seed["tenant"]
        stmt = apply_task_filters(
            select(Task).where(Task.tenant_key == tenant),
            status=None,
            priority=None,
            task_type_id=None,
            due_before=None,
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
        """THE DEFECT (U8-F1). Same token, same shape as the task above -- must be
        found by list_projects' query once description is added to the search."""
        tenant = matched_pair_seed["tenant"]
        product = matched_pair_seed["product"]

        rows = await _PROJECT_REPO.list_projects(db_session, tenant, product_id=product.id, search=_TOKEN)

        assert {r.name for r in rows} == {"Wombat tracker"}, (
            f"list_projects(query={_TOKEN!r}) matched {[r.name for r in rows]} of 1 expected -- "
            "description is not in the projects search OR-clause (U8-F1)"
        )

    @pytest.mark.asyncio
    async def test_project_query_finds_by_project_alias(self, db_session, matched_pair_seed):
        """THE DEFECT (U8-F2). project_alias (Project.alias, the 6-char code e.g.
        'QWL2H8') must be searchable, same as taxonomy_alias already is."""
        tenant = matched_pair_seed["tenant"]
        product = matched_pair_seed["product"]

        rows = await _PROJECT_REPO.list_projects(db_session, tenant, product_id=product.id, search="ZQ9K7M")

        assert {r.name for r in rows} == {"Wombat tracker"}, (
            "list_projects(query='ZQ9K7M') did not find the project by its project_alias (U8-F2)"
        )


# ---------------------------------------------------------------------------
# Part 2 -- escaping guard on the two NEW fields (description, alias)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def wildcard_probe_new_fields(db_session):
    """Five projects: one with a literal '%' in its description, one with a
    literal '_' in its description, one with a literal '%' in its alias, one
    with a literal '_' in its alias, and one entirely plain control. None of
    their NAMES contain '%'/'_' -- only description/alias do, so a match on
    those characters can only come from the new fields."""
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
    """The new fields go through the SAME escaped needle as name/id/taxonomy_alias
    (aa249c979) -- no second escaping path. '%'/'_' must stay literal on both."""

    @pytest.mark.asyncio
    async def test_bare_percent_matches_only_the_literal_percent_rows(self, db_session, wildcard_probe_new_fields):
        tenant = wildcard_probe_new_fields["tenant"]
        product = wildcard_probe_new_fields["product"]

        rows = await _PROJECT_REPO.list_projects(db_session, tenant, product_id=product.id, search="%")

        # Escaped: '%' is a literal character, matching only the two rows whose
        # description/alias actually contains it. Unescaped (the bug): '%' is
        # the SQL wildcard and matches all 5 rows.
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
        """Both-sides guard: an ordinary substring search on the NEW field must
        keep working. If this goes red, suspect the fix, not the escaping."""
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


# ---------------------------------------------------------------------------
# Part 3 -- search_memory reaches git commit messages (approved fix, BE-9469)
# ---------------------------------------------------------------------------


class TestSearchMemoryReachesCommitMessages:
    """Deliverable 3. RED (measured before any fix): neither the FTS document
    (``_FTS_DOCUMENT_SQL``) nor the ILIKE fallback (``_ilike_stmt``) in
    ``ProductMemoryRepository`` included ``git_commits`` -- a distinctive commit
    message stored in a closeout was not findable by ``search_memory``. Measured
    and reviewed under the BE-9469 project ruling per the brief's
    verify-then-propose pre-ruling; approved to build both paths, paired with a
    migration keeping ``idx_pme_fts`` in sync (``ce_0096_pme_fts_git_commits_be9469.py``).

    GREEN (this class, after the fix): a commit message is reachable via BOTH
    match paths independently -- constraint 2 was "both paths or neither", so
    each path gets its own assertion rather than one test that could pass by
    either engine alone."""

    @pytest.mark.asyncio
    async def test_commit_message_found_via_the_fts_path(self, db_session, test_product, test_tenant_key):
        """A full-word phrase plainto_tsquery can stem -- exercises _FTS_DOCUMENT_SQL."""
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
        """A partial-word substring plainto_tsquery cannot stem -- forces the
        _ilike_stmt fallback, same idiom as test_ilike_fallback_partial_word in
        test_be6082_memory_fts.py ('tena' -> 'tenant')."""
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

        # 'quantumwid' is not a lexeme of 'quantumwidget' -> plainto_tsquery
        # yields no FTS hit, so the repo falls back to ILIKE '%quantumwid%'.
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
