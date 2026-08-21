# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9468 follow-ups -- three defects black-box QA found in the read layer we shipped,
reproduced against a live 471-project board within 30 minutes of the code landing.

Fix 1 -- ``ProjectRepository._build_list_conditions`` builds its search predicate with a
bare ``ilike(f"%{search}%")`` and no ``escape=`` argument. ``%`` and ``_`` are SQL LIKE
metacharacters: an unescaped ``%`` matches every row (a search that reads narrow and
returns the whole board), and an unescaped ``_`` silently matches any single character
(``foo_bar`` also matching ``fooXbar``, unnoticed). The conclusive live signal was
``%oauth%`` returning the BYTE-IDENTICAL row count to the bare word ``oauth`` -- the
``%`` were consumed as wildcards, not literals. This module reproduces that same shape at
the repository layer against a seeded slot DB, the layer the bug actually lives at.

Fix 3 -- ``TaskService.list_tasks_for_mcp`` floors ``effective_limit`` at 1 and raises
``ValidationError`` for ``limit=0``, while the sibling ``list_projects_for_mcp`` treats
``limit=0`` as "use the default". Aligning the MCP-tool schema on ``ge=0`` (fix 3, see the
boundary test in ``tests/integration/test_be9468_qa_followups_boundary.py``) is worthless
if the service still floors and raises below it -- this module pins the service-level half
of that fix.

Edition Scope: Both.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Product, Project
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.tenant import TenantManager


# A repo bound to nothing -- list/count take the session explicitly (mirrors the
# BE-6076 pagination suite's convention).
_REPO = ProjectRepository()


# ---------------------------------------------------------------------------
# Fix 1 -- search must not treat "%" / "_" as live SQL wildcards
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def wildcard_probe_projects(db_session):
    """Three projects, none containing a literal '%' or '_' in their name.

    Named so an unescaped LIKE wildcard and an escaped literal search produce
    OBSERVABLY different row counts: "oauth" matches exactly one row by a real
    substring; "%" / "_" / "%oauth%" match zero rows once escaped, because no
    seeded name contains those literal characters.
    """
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
    """Reproduces the QA table verbatim, at the repository layer against the slot DB."""

    @pytest.mark.asyncio
    async def test_bare_percent_does_not_match_the_whole_board(self, db_session, wildcard_probe_projects):
        tenant = wildcard_probe_projects["tenant"]
        product = wildcard_probe_projects["product"]

        rows = await _REPO.list_projects(db_session, tenant, product_id=product.id, search="%")

        # Escaped: "%" is a literal character none of the 3 seeded names contain.
        # Unescaped (the bug): "%" is the SQL wildcard and matches all 3.
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
        """The QA report's conclusive signal: '%oauth%' must NOT byte-match 'oauth'.

        If '%' were a live wildcard, wrapping the word in '%' would be a no-op (it
        already substring-matches) and both queries return the same rows. Escaped,
        '%oauth%' is a literal 8-character needle that appears in no seeded name, so
        it must return ZERO rows while the bare word returns exactly one.
        """
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
        """count_projects shares _build_list_conditions with list_projects -- they must
        never diverge (that is the whole point of the shared builder)."""
        tenant = wildcard_probe_projects["tenant"]
        product = wildcard_probe_projects["product"]

        total = await _REPO.count_projects(db_session, tenant, product_id=product.id, search="%")
        rows = await _REPO.list_projects(db_session, tenant, product_id=product.id, search="%")

        assert total == len(rows) == 0

    @pytest.mark.asyncio
    async def test_both_sides_guard_a_real_word_still_matches(self, db_session, wildcard_probe_projects):
        """Control: an ordinary substring search must keep working on BOTH sides of the
        fix. If this ever goes red, suspect the harness/fixture, not the escaping fix."""
        tenant = wildcard_probe_projects["tenant"]
        product = wildcard_probe_projects["product"]

        rows = await _REPO.list_projects(db_session, tenant, product_id=product.id, search="widget")

        assert {r.name for r in rows} == {"Alpha widget", "Bravo widget"}


# ---------------------------------------------------------------------------
# Fix 3 -- list_tasks_for_mcp must treat limit=0 as "use the default", not raise
# ---------------------------------------------------------------------------


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

        # list_projects_for_mcp's sibling contract: limit=0 means "use the default",
        # never a validation error. Today this raises ValidationError instead.
        response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, limit=0)

        assert response["count"] == 1
        assert response["tasks"][0]["title"] == "BE-9468 followups probe task"

    @pytest.mark.asyncio
    async def test_negative_limit_is_still_rejected(self, db_session, two_tenant_service_setup):
        """Both-sides guard: widening 0 must not widen negative values too."""
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]

        with pytest.raises(ValidationError):
            await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, limit=-1)
