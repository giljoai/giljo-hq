# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from giljo_mcp.system_prompts.service import PromptRecord, SystemPromptService


pytestmark = pytest.mark.asyncio

PRODUCT_TEXT = "PRODUCT-SCOPED orchestrator seed for FE-9408 API."
DEFAULT_TEXT = "PACKAGED SEED for FE-9408 route tests."
PRODUCT_ID = "9408f000-0000-4000-8000-000000000001"
SAVED_AT = datetime(2026, 7, 16, 9, 30, tzinfo=UTC)


async def test_default_content_is_the_seed_a_product_without_a_row_receives(db_manager):
    service = SystemPromptService(db_manager=db_manager)
    default_content = service.default_orchestrator_content()

    assert isinstance(default_content, str)
    assert default_content.strip()
    assert default_content == service._build_default_orchestrator_prompt()


class _StubService:

    def __init__(self, *, record: PromptRecord):
        self._record = record

    async def get_orchestrator_prompt(self, *, tenant_key, product_id=None):
        return self._record

    async def update_orchestrator_prompt(self, *, tenant_key, content, updated_by, product_id=None):
        return self._record

    async def reset_orchestrator_prompt(self, *, tenant_key, product_id=None):
        return self._record

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


def _product_record() -> PromptRecord:
    return PromptRecord(
        content=PRODUCT_TEXT,
        is_override=True,
        updated_at=SAVED_AT,
        updated_by="admin@example.com",
        scope="product",
    )


async def _call_all_three_routes(service):
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
            "get": await get_orchestrator_prompt(product_id=PRODUCT_ID, current_user=user),
            "put": await update_orchestrator_prompt(
                payload=OrchestratorPromptUpdateRequest(content=PRODUCT_TEXT, product_id=PRODUCT_ID),
                current_user=user,
            ),
            "reset": await reset_orchestrator_prompt(product_id=PRODUCT_ID, current_user=user),
        }


async def test_all_three_routes_carry_default_content_through_the_shared_mapper():
    responses = await _call_all_three_routes(_StubService(record=_product_record()))

    for route, response in responses.items():
        assert response.scope == "product", route
        assert response.default_content == DEFAULT_TEXT, route


async def test_existing_fields_keep_their_meaning():
    record = _product_record()

    response = (await _call_all_three_routes(_StubService(record=record)))["get"]

    assert response.content == PRODUCT_TEXT
    assert response.is_override is True
    assert response.updated_at == record.updated_at
    assert response.updated_by == "admin@example.com"


async def test_the_account_wide_fields_are_gone_from_the_response():
    from api.endpoints.system_prompts import OrchestratorPromptResponse

    fields = set(OrchestratorPromptResponse.model_fields)

    assert not {"tenant_override_exists", "tenant_override_updated_at"} & fields


async def test_mapper_answers_for_a_caller_with_no_default_to_supply():
    from api.endpoints.system_prompts import _to_response

    response = _to_response(PromptRecord(content="x", is_override=False, updated_at=None, updated_by=None))

    assert response.default_content == ""
