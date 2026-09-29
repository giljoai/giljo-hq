# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.services.template_write_paths import CrewNamingExhaustedError
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

CREW_SIZE = 5


@pytest_asyncio.fixture
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


class _TemplateCreateRequest:

    def __init__(self, product_id: str) -> None:
        self.product_id = product_id
        self.name = None
        self.role = "implementer"
        self.cli_tool = "claude"
        self.custom_suffix = None
        self.background_color = None
        self.description = None
        self.user_instructions = "seeded by the BE-9666 race test"
        self.model = None
        self.behavioral_rules = []
        self.success_criteria = []
        self.tags = []
        self.is_default = False
        self.is_active = True
        self.category = "role"


def _product_service(db_manager, tenant_key: str, session=None):
    from giljo_mcp.services.product_service import ProductService

    return ProductService(db_manager=db_manager, tenant_key=tenant_key, test_session=session)


async def _live_agent_names(session, tenant_key: str) -> list[str]:
    stmt = select(AgentTemplate.name).where(
        AgentTemplate.tenant_key == tenant_key,
        AgentTemplate.deleted_at.is_(None),
    )
    with tenant_session_context(session, tenant_key):
        return sorted((await session.execute(stmt)).scalars().all())




async def test_concurrent_product_creates_all_succeed_with_distinct_crew_names(db_manager, tenant_key: str):

    async def _create(index: int):
        service = _product_service(db_manager, tenant_key)
        return await service.create_product(name=f"BE-9666 concurrent {index} {uuid.uuid4().hex[:6]}")

    results = await asyncio.gather(*[_create(i) for i in range(4)], return_exceptions=True)

    failures = [repr(r) for r in results if isinstance(r, BaseException)]
    assert not failures, f"a concurrent product create failed: {failures}"

    async with db_manager.get_session_async() as session:
        names = await _live_agent_names(session, tenant_key)
    assert len(names) == 4 * CREW_SIZE, f"expected 4 crews of {CREW_SIZE}, got {len(names)}: {names}"
    assert len(set(names)) == len(names), f"two live agents share a name: {names}"


async def test_a_retried_crew_still_gets_its_junction_rows(db_manager, tenant_key: str):
    from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment

    async def _create(index: int):
        service = _product_service(db_manager, tenant_key)
        return await service.create_product(name=f"BE-9666 junction {index} {uuid.uuid4().hex[:6]}")

    results = await asyncio.gather(*[_create(i) for i in range(4)], return_exceptions=True)
    assert not [r for r in results if isinstance(r, BaseException)], results

    async with db_manager.get_session_async() as session:
        with tenant_session_context(session, tenant_key):
            agent_ids = set(
                (
                    await session.execute(
                        select(AgentTemplate.id).where(
                            AgentTemplate.tenant_key == tenant_key,
                            AgentTemplate.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            junction = (
                await session.execute(
                    select(ProductAgentAssignment.template_id, ProductAgentAssignment.is_active).where(
                        ProductAgentAssignment.tenant_key == tenant_key
                    )
                )
            ).all()

    assert len(agent_ids) == 4 * CREW_SIZE
    assert {row[0] for row in junction} == agent_ids, "an agent was seeded without its switch row"
    assert all(row[1] for row in junction), "a factory crew must arrive switched on"


async def test_concurrent_single_agent_creates_also_get_distinct_names(db_manager, tenant_key: str):
    from giljo_mcp.services.template_service import TemplateService

    product = await _product_service(db_manager, tenant_key).create_product(
        name=f"BE-9666 agent race {uuid.uuid4().hex[:6]}"
    )

    async def _create():
        async with db_manager.get_session_async() as session:
            service = TemplateService(db_manager=db_manager, tenant_manager=None, session=session)
            return await service.create_template_from_request(
                session, _TemplateCreateRequest(product.id), tenant_key, created_by="be9666"
            )

    results = await asyncio.gather(*[_create() for _ in range(4)], return_exceptions=True)

    failures = [repr(r) for r in results if isinstance(r, BaseException)]
    assert not failures, f"a concurrent agent create failed: {failures}"

    names = [r.name for r in results]
    assert len(set(names)) == len(names), f"two agents were created with one name: {names}"




async def test_single_agent_race_exhaustion_refuses_cleanly_instead_of_500(db_manager, db_session, tenant_key: str):
    from unittest.mock import patch

    from sqlalchemy.exc import IntegrityError

    from giljo_mcp.services.template_service import TemplateService

    product = await _product_service(db_manager, tenant_key, session=db_session).create_product(
        name=f"BE-9666 single-agent exhaustion {uuid.uuid4().hex[:6]}"
    )
    service = TemplateService(db_manager=db_manager, tenant_manager=None, session=db_session)

    conflict = IntegrityError(
        "INSERT",
        {},
        Exception('duplicate key value violates unique constraint "uq_template_tenant_name_version"'),
    )

    with patch.object(TemplateService, "add_and_commit_template", side_effect=conflict):
        with pytest.raises(CrewNamingExhaustedError) as exc:
            await service.create_template_from_request(
                db_session, _TemplateCreateRequest(product.id), tenant_key, created_by="be9666"
            )

    assert exc.value.code == "CREW_NAMING_EXHAUSTED"
    assert exc.value.default_status_code < 500, "a naming refusal must not be a server error"


async def test_single_agent_non_name_conflict_integrity_error_still_raises(db_manager, db_session, tenant_key: str):
    from unittest.mock import patch

    from sqlalchemy.exc import IntegrityError

    from giljo_mcp.services.template_service import TemplateService

    product = await _product_service(db_manager, tenant_key, session=db_session).create_product(
        name=f"BE-9666 single-agent genuine fault {uuid.uuid4().hex[:6]}"
    )
    service = TemplateService(db_manager=db_manager, tenant_manager=None, session=db_session)

    genuine_fault = IntegrityError(
        "INSERT",
        {},
        Exception('null value in column "role" violates not-null constraint'),
    )

    with patch.object(TemplateService, "add_and_commit_template", side_effect=genuine_fault):
        with pytest.raises(IntegrityError):
            await service.create_template_from_request(
                db_session, _TemplateCreateRequest(product.id), tenant_key, created_by="be9666"
            )


async def test_single_agent_name_conflict_within_budget_still_succeeds(db_manager, db_session, tenant_key: str):
    from unittest.mock import patch

    from sqlalchemy.exc import IntegrityError

    from giljo_mcp.services.template_service import TemplateService
    from giljo_mcp.services.template_write_paths import AGENT_NAME_RACE_ATTEMPTS

    product = await _product_service(db_manager, tenant_key, session=db_session).create_product(
        name=f"BE-9666 single-agent within budget {uuid.uuid4().hex[:6]}"
    )
    service = TemplateService(db_manager=db_manager, tenant_manager=None, session=db_session)
    real_add_and_commit_template = TemplateService.add_and_commit_template
    conflict = IntegrityError(
        "INSERT",
        {},
        Exception('duplicate key value violates unique constraint "uq_template_tenant_name_version"'),
    )

    calls = {"n": 0}

    async def flaky(self, session, template):
        calls["n"] += 1
        if calls["n"] < AGENT_NAME_RACE_ATTEMPTS:
            raise conflict
        return await real_add_and_commit_template(self, session, template)

    with patch.object(TemplateService, "add_and_commit_template", flaky):
        result = await service.create_template_from_request(
            db_session, _TemplateCreateRequest(product.id), tenant_key, created_by="be9666"
        )

    assert result is not None
    assert calls["n"] == AGENT_NAME_RACE_ATTEMPTS, "expected the last attempt to be the one that wins"


async def test_sequential_product_creates_keep_naming_crews_at_the_next_suffix(db_manager, db_session, tenant_key: str):
    service = _product_service(db_manager, tenant_key, session=db_session)

    for index in range(4):
        product = await service.create_product(name=f"BE-9666 sequential {index} {uuid.uuid4().hex[:6]}")
        assert product is not None

    names = await _live_agent_names(db_session, tenant_key)
    assert len(set(names)) == 4 * CREW_SIZE, f"duplicate crew names persisted: {names}"
    for suffix in ("implementer", "implementer-2", "implementer-3", "implementer-4"):
        assert suffix in names, f"missing {suffix} in {names}"




async def test_crew_with_no_free_suffix_refuses_instead_of_raising_a_db_error(db_manager, db_session, tenant_key: str):
    from giljo_mcp.template_validation import MAX_NAME_SUFFIX

    service = _product_service(db_manager, tenant_key, session=db_session)
    first = await service.create_product(name=f"BE-9666 full {uuid.uuid4().hex[:6]}")

    with tenant_session_context(db_session, tenant_key):
        for n in range(2, MAX_NAME_SUFFIX + 1):
            db_session.add(
                AgentTemplate(
                    id=str(uuid.uuid4()),
                    tenant_key=tenant_key,
                    product_id=first.id,
                    name=f"implementer-{n}",
                    category="role",
                    role="implementer",
                    cli_tool="claude",
                    description="occupies a crew suffix",
                    system_instructions="x",
                    user_instructions="x",
                    version="1.0.0",
                )
            )
        await db_session.commit()

    with pytest.raises(CrewNamingExhaustedError) as exc:
        await service.create_product(name=f"BE-9666 overflow {uuid.uuid4().hex[:6]}")

    assert exc.value.code == "CREW_NAMING_EXHAUSTED"
    assert exc.value.default_status_code < 500, "a naming refusal must not be a server error"


async def test_a_name_taken_at_another_version_still_blocks_the_crew_suffix(db_manager, db_session, tenant_key: str):
    service = _product_service(db_manager, tenant_key, session=db_session)
    first = await service.create_product(name=f"BE-9666 versions {uuid.uuid4().hex[:6]}")

    with tenant_session_context(db_session, tenant_key):
        db_session.add(
            AgentTemplate(
                id=str(uuid.uuid4()),
                tenant_key=tenant_key,
                product_id=first.id,
                name="implementer-2",
                category="role",
                role="implementer",
                cli_tool="claude",
                description="same name, different version",
                system_instructions="x",
                user_instructions="x",
                version="1.0.0",
            )
        )
        await db_session.commit()

    second = await service.create_product(name=f"BE-9666 next {uuid.uuid4().hex[:6]}")
    assert second is not None

    names = await _live_agent_names(db_session, tenant_key)
    assert names.count("implementer-2") == 1, f"the guard reused a taken name: {names}"
    assert "implementer-3" in names, f"the crew should have moved past the squatter: {names}"
