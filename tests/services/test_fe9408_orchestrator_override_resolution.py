# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.services.mission_assembly import gate_identity_source
from giljo_mcp.services.orchestrator_product_resolver import (
    compose_identity_with_provenance,
    resolve_orchestrator_override,
    resolve_product_name,
)
from giljo_mcp.system_prompts.identity_provenance import append_identity_source, format_identity_source
from giljo_mcp.system_prompts.service import (
    SCOPE_DEFAULT,
    SCOPE_PRODUCT,
    SCOPE_TENANT,
    SystemPromptService,
    read_orchestrator_override,
)
from giljo_mcp.template_seeder import compose_orchestrator_identity


TENANT_TEXT = "TENANT-WIDE orchestrator seed for FE-9408 resolution."
PRODUCT_TEXT = "PRODUCT-SCOPED orchestrator seed for FE-9408 resolution."
PRODUCT_NAME = "Acme Widgets"
SAVED_AT = datetime(2026, 7, 16, 9, 30, tzinfo=UTC)




def test_tenant_line_names_the_rung_and_the_date():
    assert (
        format_identity_source(SCOPE_TENANT, updated_at=SAVED_AT)
        == "identity source: tenant-wide override, saved 2026-07-16"
    )


def test_product_line_names_the_product():
    assert (
        format_identity_source(SCOPE_PRODUCT, updated_at=SAVED_AT, product_name=PRODUCT_NAME)
        == "identity source: product override (Acme Widgets), saved 2026-07-16"
    )


def test_default_line_says_built_in_and_claims_no_override():
    line = format_identity_source(SCOPE_DEFAULT)
    assert line == "identity source: built-in default"
    assert "override" not in line, "the built-in default must never read as an override"


def test_an_unparseable_stored_date_drops_the_clause_instead_of_saying_saved_none():
    assert format_identity_source(SCOPE_TENANT, updated_at=None) == "identity source: tenant-wide override"


def test_an_unreadable_product_name_drops_the_parenthetical_only():
    assert (
        format_identity_source(SCOPE_PRODUCT, updated_at=SAVED_AT, product_name=None)
        == "identity source: product override, saved 2026-07-16"
    )


def test_the_line_is_neutral_about_whose_product_it_is():
    line = format_identity_source(SCOPE_PRODUCT, updated_at=SAVED_AT, product_name=PRODUCT_NAME)
    assert "your project" not in line
    assert "this project" not in line


def test_append_puts_the_line_last_behind_a_blank_line():
    assert append_identity_source("BODY", "identity source: built-in default") == (
        "BODY\n\nidentity source: built-in default"
    )


def test_provenance_is_withheld_with_the_identity_it_describes():
    assert gate_identity_source("some identity", "identity source: built-in default") == (
        "identity source: built-in default"
    )
    assert gate_identity_source(None, "identity source: tenant-wide override, saved 2026-07-16") is None
    assert gate_identity_source("", "identity source: built-in default") is None




def _mission_service(db_manager, *, project_row, product_name: str | None = PRODUCT_NAME):
    from giljo_mcp.services.mission_service import MissionService

    svc = MissionService.__new__(MissionService)
    svc._logger = logging.getLogger("test_fe9408_resolution")
    svc.db_manager = db_manager
    svc.tenant_manager = None
    svc._repo = MagicMock()
    svc._repo.get_project_by_id = AsyncMock(return_value=project_row)
    svc._repo.get_product_name = AsyncMock(return_value=product_name)
    return svc


def _job(project_id: str | None = "proj-fe9408"):
    return SimpleNamespace(job_type="orchestrator", template_id=None, project_id=project_id, job_id="job-fe9408")


def _execution():
    return SimpleNamespace(agent_display_name="orchestrator", agent_id="agent-fe9408")


def _project_row(product_id: str | None):
    return SimpleNamespace(id="proj-fe9408", product_id=product_id, execution_mode="multi_terminal")


async def _seed(db_manager, db_session, tenant_key, *, product_id=None, tenant=False, product=False):
    service = SystemPromptService(db_manager=db_manager)
    if tenant:
        await service.update_orchestrator_prompt(
            tenant_key=tenant_key, content=TENANT_TEXT, updated_by="admin", session=db_session
        )
    if product:
        await service.update_orchestrator_prompt(
            tenant_key=tenant_key,
            content=PRODUCT_TEXT,
            updated_by="admin",
            product_id=product_id,
            session=db_session,
        )
    await db_session.commit()


@pytest.mark.asyncio
class TestWidenedResolution:
    async def test_product_rung_reports_its_date_and_its_product(self, db_manager, db_session, test_tenant_key):
        product_id = str(uuid.uuid4())
        await _seed(db_manager, db_session, test_tenant_key, product_id=product_id, tenant=True, product=True)

        svc = _mission_service(db_manager, project_row=_project_row(product_id))
        resolved = await resolve_orchestrator_override(
            svc, db_session, _job(), _execution(), test_tenant_key, _project_row(product_id)
        )

        assert resolved.content == PRODUCT_TEXT
        assert resolved.scope == SCOPE_PRODUCT
        assert resolved.updated_at is not None
        assert resolved.product_id == product_id

    async def test_tenant_rung_reports_its_date_and_no_product(self, db_manager, db_session, test_tenant_key):
        product_id = str(uuid.uuid4())
        await _seed(db_manager, db_session, test_tenant_key, product_id=product_id, tenant=True, product=False)

        svc = _mission_service(db_manager, project_row=_project_row(product_id))
        resolved = await resolve_orchestrator_override(
            svc, db_session, _job(), _execution(), test_tenant_key, _project_row(product_id)
        )

        assert resolved.content == TENANT_TEXT
        assert resolved.scope == SCOPE_TENANT
        assert resolved.updated_at is not None
        assert resolved.product_id is None

    async def test_default_rung_reports_nothing_to_attribute(self, db_manager, db_session, test_tenant_key):
        svc = _mission_service(db_manager, project_row=_project_row(str(uuid.uuid4())))
        resolved = await resolve_orchestrator_override(
            svc, db_session, _job(), _execution(), test_tenant_key, _project_row(None)
        )

        assert resolved.content is None
        assert resolved.scope == SCOPE_DEFAULT
        assert resolved.updated_at is None
        assert resolved.product_id is None

    async def test_the_degraded_branch_still_never_raises(self, db_manager, db_session, test_tenant_key):
        svc = _mission_service(db_manager, project_row=_project_row(str(uuid.uuid4())))
        svc._repo.get_project_by_id = AsyncMock(side_effect=RuntimeError("database is on fire"))

        resolved = await resolve_orchestrator_override(
            svc, db_session, _job(project_id=None), _execution(), test_tenant_key, None
        )

        assert resolved.content is None
        assert resolved.scope == SCOPE_DEFAULT
        assert resolved.updated_at is None
        assert resolved.product_id is None

    async def test_the_staging_read_reports_the_same_rung(self, db_manager, db_session, test_tenant_key):
        product_id = str(uuid.uuid4())
        await _seed(db_manager, db_session, test_tenant_key, product_id=product_id, tenant=True, product=True)

        staging = await read_orchestrator_override(
            db_manager=db_manager, tenant_key=test_tenant_key, product_id=product_id, session=db_session
        )
        svc = _mission_service(db_manager, project_row=_project_row(product_id))
        mission = await resolve_orchestrator_override(
            svc, db_session, _job(), _execution(), test_tenant_key, _project_row(product_id)
        )

        assert staging.content == mission.content == PRODUCT_TEXT
        assert staging.scope == mission.scope == SCOPE_PRODUCT
        assert staging.updated_at == mission.updated_at
        assert staging.product_id == mission.product_id == product_id

    async def test_an_unusable_product_id_degrades_the_staging_read_to_the_tenant_rung(
        self, db_manager, db_session, test_tenant_key
    ):
        await _seed(db_manager, db_session, test_tenant_key, tenant=True)

        staging = await read_orchestrator_override(
            db_manager=db_manager, tenant_key=test_tenant_key, product_id="not-a-uuid", session=db_session
        )

        assert staging.content == TENANT_TEXT
        assert staging.scope == SCOPE_TENANT

    async def test_a_failed_product_name_lookup_costs_the_label_and_nothing_else(
        self, db_manager, db_session, test_tenant_key
    ):
        svc = _mission_service(db_manager, project_row=_project_row(None))
        svc._repo.get_product_name = AsyncMock(side_effect=RuntimeError("product row unreadable"))

        assert await resolve_product_name(svc, db_session, test_tenant_key, str(uuid.uuid4())) is None




@pytest.mark.asyncio
class TestServedContentIsUnchanged:

    async def _served(self, db_manager, db_session, tenant_key, *, product_id):
        svc = _mission_service(db_manager, project_row=_project_row(product_id))
        return await compose_identity_with_provenance(
            svc,
            db_session,
            _job(),
            _execution(),
            tenant_key,
            _project_row(product_id),
            tool="multi_terminal",
            role=None,
        )

    async def test_product_scope_is_composition_plus_one_line(self, db_manager, db_session, test_tenant_key):
        product_id = str(uuid.uuid4())
        await _seed(db_manager, db_session, test_tenant_key, product_id=product_id, tenant=True, product=True)

        identity, source, scope = await self._served(db_manager, db_session, test_tenant_key, product_id=product_id)

        assert (
            identity == compose_orchestrator_identity(PRODUCT_TEXT, tool="multi_terminal", role=None) + f"\n\n{source}"
        )
        assert source.startswith(f"identity source: product override ({PRODUCT_NAME}), saved ")
        assert scope == SCOPE_PRODUCT

    async def test_tenant_scope_is_composition_plus_one_line(self, db_manager, db_session, test_tenant_key):
        product_id = str(uuid.uuid4())
        await _seed(db_manager, db_session, test_tenant_key, product_id=product_id, tenant=True)

        identity, source, scope = await self._served(db_manager, db_session, test_tenant_key, product_id=product_id)

        assert (
            identity == compose_orchestrator_identity(TENANT_TEXT, tool="multi_terminal", role=None) + f"\n\n{source}"
        )
        assert source.startswith("identity source: tenant-wide override, saved ")
        assert scope == SCOPE_TENANT

    async def test_default_scope_is_composition_plus_one_line(self, db_manager, db_session, test_tenant_key):
        identity, source, scope = await self._served(
            db_manager, db_session, test_tenant_key, product_id=str(uuid.uuid4())
        )

        assert identity == compose_orchestrator_identity(None, tool="multi_terminal", role=None) + f"\n\n{source}"
        assert source == "identity source: built-in default"
        assert scope == SCOPE_DEFAULT

    async def test_the_conductors_role_trim_is_preserved_under_the_append(
        self, db_manager, db_session, test_tenant_key
    ):
        svc = _mission_service(db_manager, project_row=_project_row(None))
        identity, source, _scope = await compose_identity_with_provenance(
            svc,
            db_session,
            _job(),
            _execution(),
            test_tenant_key,
            _project_row(None),
            tool="multi_terminal",
            role="conductor",
        )

        assert (
            identity == compose_orchestrator_identity(None, tool="multi_terminal", role="conductor") + f"\n\n{source}"
        )
        assert len(identity) < len(compose_orchestrator_identity(None, tool="multi_terminal", role=None)), (
            "the conductor's trimmed body must survive the append -- if this grew back, "
            "the append is composing off the untrimmed identity"
        )
