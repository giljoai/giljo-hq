# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9408 — the three provenance fields on the orchestrator-prompt routes.

The editor cannot warn about an override it cannot see. ``scope`` already says which
rung WON; these fields say what is standing BEHIND it:

  tenant_override_exists      a tenant-wide row exists, whichever rung won
  tenant_override_updated_at  when it was saved
  default_content             the effective built-in seed, to compare a save against

The load-bearing case is the one the ladder structurally cannot report: a PRODUCT
override wins, and a tenant-wide row is sitting behind it governing every OTHER
product. ``_fetch_ladder`` short-circuits at the product rung by design, so only the
sibling read can answer it -- and every pre-Aug-2026 save could ONLY be tenant-wide,
which makes that the shape on real installs, not an exotic one.

Two layers, because the fields have two failure modes: the sibling QUERY can fail to
see a shadowed row (service tests, real DB), and a ROUTE can fail to pass the extras
through the shared mapper (route tests, stub service -- all three routes, since
BE-9385d's "one mapping, three routes" only holds if all three actually call it).

Parallel-safe: DB-touching tests use the db_session fixture (TransactionalTestContext,
rollback at teardown). No module-level mutable state. Edition Scope: Both.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from giljo_mcp.system_prompts.service import PromptRecord, SystemPromptService


pytestmark = pytest.mark.asyncio

TENANT_TEXT = "TENANT-WIDE orchestrator seed for FE-9408 API."
PRODUCT_TEXT = "PRODUCT-SCOPED orchestrator seed for FE-9408 API."


def _tenant_key() -> str:
    return f"tk_fe9408_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Service layer -- the sibling query that sees a SHADOWED tenant row
# ---------------------------------------------------------------------------


async def test_tenant_row_is_visible_even_when_the_product_rung_wins(db_manager, db_session):
    """The case the ladder cannot report, and the reason this query exists."""
    service = SystemPromptService(db_manager=db_manager)
    tenant_key = _tenant_key()
    product_id = str(uuid.uuid4())

    await service.update_orchestrator_prompt(
        tenant_key=tenant_key, content=TENANT_TEXT, updated_by="fe9408", session=db_session
    )
    await service.update_orchestrator_prompt(
        tenant_key=tenant_key,
        content=PRODUCT_TEXT,
        updated_by="fe9408",
        product_id=product_id,
        session=db_session,
    )

    # The ladder answers "the product override won" -- and says nothing about the
    # tenant-wide row still governing every other product.
    resolved = await service.get_orchestrator_prompt(tenant_key=tenant_key, product_id=product_id, session=db_session)
    assert resolved.scope == "product"
    assert resolved.content == PRODUCT_TEXT

    # The sibling read is what makes that row visible.
    tenant_row = await service.read_tenant_override_row(tenant_key=tenant_key, session=db_session)
    assert tenant_row is not None
    assert tenant_row["content"] == TENANT_TEXT
    assert tenant_row["updated_at"] is not None


async def test_tenant_row_is_none_when_only_a_product_override_exists(db_manager, db_session):
    service = SystemPromptService(db_manager=db_manager)
    tenant_key = _tenant_key()
    product_id = str(uuid.uuid4())

    await service.update_orchestrator_prompt(
        tenant_key=tenant_key,
        content=PRODUCT_TEXT,
        updated_by="fe9408",
        product_id=product_id,
        session=db_session,
    )

    assert await service.read_tenant_override_row(tenant_key=tenant_key, session=db_session) is None


async def test_tenant_row_is_scoped_to_its_own_tenant(db_manager, db_session):
    """Every query filters by tenant_key -- a neighbour's override is not ours."""
    service = SystemPromptService(db_manager=db_manager)
    mine, theirs = _tenant_key(), _tenant_key()

    await service.update_orchestrator_prompt(
        tenant_key=theirs, content=TENANT_TEXT, updated_by="fe9408", session=db_session
    )

    assert await service.read_tenant_override_row(tenant_key=mine, session=db_session) is None
    assert await service.read_tenant_override_row(tenant_key=theirs, session=db_session) is not None


async def test_tenant_row_read_requires_a_tenant_key(db_manager, db_session):
    service = SystemPromptService(db_manager=db_manager)
    with pytest.raises(ValueError, match="tenant_key"):
        await service.read_tenant_override_row(tenant_key="", session=db_session)


async def test_default_content_is_the_seed_the_ladder_falls_back_to(db_manager):
    """Same text, one source -- otherwise the editor compares against a stale copy."""
    service = SystemPromptService(db_manager=db_manager)
    default_content = service.default_orchestrator_content()

    assert isinstance(default_content, str)
    assert default_content.strip()
    assert default_content == service._build_default_orchestrator_prompt()


# ---------------------------------------------------------------------------
# Route layer -- all three routes carry the extras through the shared mapper
# ---------------------------------------------------------------------------

DEFAULT_TEXT = "PACKAGED SEED for FE-9408 route tests."
TENANT_SAVED_AT = datetime(2026, 7, 16, 9, 30, tzinfo=UTC)


class _StubService:
    """A SystemPromptService stand-in: the routes' wiring is what is under test."""

    def __init__(self, *, record: PromptRecord, tenant_row: dict | None):
        self._record = record
        self._tenant_row = tenant_row
        self.tenant_row_reads: list[str] = []

    async def get_orchestrator_prompt(self, *, tenant_key, product_id=None):
        return self._record

    async def update_orchestrator_prompt(self, *, tenant_key, content, updated_by, product_id=None):
        return self._record

    async def reset_orchestrator_prompt(self, *, tenant_key, product_id=None):
        return self._record

    async def read_tenant_override_row(self, *, tenant_key):
        self.tenant_row_reads.append(tenant_key)
        return self._tenant_row

    def default_orchestrator_content(self) -> str:
        return DEFAULT_TEXT


def _admin(tenant_key: str = "tk_fe9408_route"):
    return SimpleNamespace(
        id="admin-fe9408",
        username="admin",
        email="admin@example.com",
        role="admin",
        tenant_key=tenant_key,
    )


def _product_wins_record() -> PromptRecord:
    return PromptRecord(
        content=PRODUCT_TEXT,
        is_override=True,
        updated_at=TENANT_SAVED_AT + timedelta(days=3),
        updated_by="admin@example.com",
        scope="product",
    )


async def _call_all_three_routes(service):
    """Return {route_name: response} for GET, PUT and POST-reset."""
    from api.endpoints.system_prompts import (
        OrchestratorPromptUpdateRequest,
        get_orchestrator_prompt,
        reset_orchestrator_prompt,
        update_orchestrator_prompt,
    )

    user = _admin()
    with patch("api.app_state.state") as mock_state:
        mock_state.system_prompt_service = service
        return {
            "get": await get_orchestrator_prompt(current_user=user),
            "put": await update_orchestrator_prompt(
                payload=OrchestratorPromptUpdateRequest(content=PRODUCT_TEXT), current_user=user
            ),
            "reset": await reset_orchestrator_prompt(current_user=user),
        }


async def test_all_three_routes_report_a_shadowed_tenant_override():
    """DoD: product override present + tenant row present -> exists is True everywhere."""
    service = _StubService(
        record=_product_wins_record(),
        tenant_row={"content": TENANT_TEXT, "updated_by": "admin@example.com", "updated_at": TENANT_SAVED_AT},
    )

    responses = await _call_all_three_routes(service)

    for route, response in responses.items():
        assert response.scope == "product", route
        assert response.tenant_override_exists is True, route
        assert response.tenant_override_updated_at == TENANT_SAVED_AT.isoformat(), route
        assert response.default_content == DEFAULT_TEXT, route
    # One read per route, each scoped to the caller's tenant.
    assert service.tenant_row_reads == ["tk_fe9408_route"] * 3


async def test_all_three_routes_report_no_tenant_override_when_there_is_none():
    service = _StubService(record=_product_wins_record(), tenant_row=None)

    responses = await _call_all_three_routes(service)

    for route, response in responses.items():
        assert response.tenant_override_exists is False, route
        assert response.tenant_override_updated_at is None, route
        # default_content ships regardless -- the no-op save guard needs it on every rung.
        assert response.default_content == DEFAULT_TEXT, route


async def test_existing_fields_are_untouched_by_the_new_ones():
    """The provenance fields are additive; scope/content/updated_at keep their meaning."""
    record = _product_wins_record()
    service = _StubService(
        record=record,
        tenant_row={"content": TENANT_TEXT, "updated_by": "admin@example.com", "updated_at": TENANT_SAVED_AT},
    )

    response = (await _call_all_three_routes(service))["get"]

    assert response.content == PRODUCT_TEXT
    assert response.is_override is True
    assert response.updated_at == record.updated_at
    assert response.updated_by == "admin@example.com"
    # The winning row's timestamp and the tenant row's are DIFFERENT values; a mapper
    # that confused them would pass a sloppier assertion than this one.
    assert response.updated_at.isoformat() != response.tenant_override_updated_at


async def test_mapper_answers_for_a_caller_with_no_provenance_to_supply():
    """_to_response keeps its one-argument shape (BE-9385d: one mapping, three routes)."""
    from api.endpoints.system_prompts import _to_response

    response = _to_response(PromptRecord(content="x", is_override=False, updated_at=None, updated_by=None))

    assert response.tenant_override_exists is False
    assert response.tenant_override_updated_at is None
    assert response.default_content == ""
