# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import re
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from giljo_mcp.config.defaults import DEFAULT_FIELD_PRIORITY
from giljo_mcp.models.products import Product
from giljo_mcp.services.product_service import ProductService
from giljo_mcp.services.product_tuning_service import ProductTuningService
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio

ALL_SECTIONS = ["description", "tech_stack", "architecture", "core_features", "quality_standards"]


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    return json.loads(result.content[0].text)


async def _seed_product(db_manager, tenant_key: str, label: str) -> Product:
    service = ProductService(db_manager, tenant_key)
    return await service.create_product(
        name=f"BE0083 {label} {uuid4().hex[:6]}",
        description=f"{label} description with stored text",
        project_path=f"/work/{label.lower()}-{uuid4().hex[:6]}",
        tech_stack={
            "programming_languages": f"{label}Lang",
            "backend_frameworks": f"{label}Backend",
            "databases_storage": f"{label}DB",
            "infrastructure": f"{label}Infra",
        },
        architecture={"primary_pattern": f"{label} pattern", "api_style": f"{label} api"},
        core_features=f"{label} core features",
    )


async def _prompt_for(db_manager, tenant_key: str, product_id: str, sections: list[str]) -> str:
    service = ProductTuningService(db_manager, tenant_key)

    async def _user_configs(_session, _user_id):
        return DEFAULT_FIELD_PRIORITY, {}

    service._get_user_configs = _user_configs
    result = await service.assemble_tuning_prompt(product_id=product_id, user_id=str(uuid4()), sections=sections)
    return result["prompt"]


async def _cleanup(db_manager, tenant_key: str) -> None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
        await session.commit()


@pytest_asyncio.fixture
async def account(db_manager, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    tenant_key = TenantManager.generate_tenant_key()
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)
    try:
        yield (lambda: create_connected_server_and_client_session(mcp_sdk_server.mcp)), tenant_key
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior
        await _cleanup(db_manager, tenant_key)


class TestTwoProductsOneAccount:
    async def test_prompt_for_one_product_never_carries_the_other(self, account, db_manager):
        _client, tenant_key = account
        a = await _seed_product(db_manager, tenant_key, "Alpha")
        b = await _seed_product(db_manager, tenant_key, "Beta")

        for mine, other in ((a, b), (b, a)):
            prompt = await _prompt_for(db_manager, tenant_key, str(mine.id), ALL_SECTIONS)
            assert str(mine.id) in prompt
            assert mine.name in prompt
            assert str(other.id) not in prompt
            assert other.name not in prompt
            assert other.project_path not in prompt
            for marker in (other.name.split()[1], f"{other.name.split()[1]}Lang", f"{other.name.split()[1]}DB"):
                assert marker not in prompt


class TestPromptFinalStepSucceedsOnPopulatedProduct:
    async def _follow_prompt(self, client, product_id: str, prompt: str, proposals: list[dict]) -> dict:
        args = {"product_id": product_id, "proposals": proposals, "overall_summary": "BE-0083 scripted review"}
        if re.search(r"force\s*=\s*true", prompt, re.IGNORECASE):
            args["force"] = True
        async with client() as session:
            result = await session.call_tool("apply_context_tuning", args)
        return _payload(result)

    async def _read_tech_stack(self, client, product_id: str) -> dict:
        async with client() as session:
            result = await session.call_tool("get_context", {"categories": ["tech_stack"], "product_id": product_id})
        return _payload(result)["data"]["tech_stack"]

    async def test_values_are_saved_and_read_back(self, account, db_manager):
        client, tenant_key = account
        product = await _seed_product(db_manager, tenant_key, "Gamma")
        pid = str(product.id)
        prompt = await _prompt_for(db_manager, tenant_key, pid, ALL_SECTIONS)

        proposals = [
            {"section": "description", "drift_detected": True, "proposed_value": "Reviewed description"},
            {
                "section": "tech_stack",
                "drift_detected": True,
                "proposed_value": {"infrastructure": "Reviewed infra", "databases_storage": "Reviewed DB"},
            },
            {
                "section": "architecture",
                "drift_detected": True,
                "proposed_value": {"primary_pattern": "Reviewed pattern"},
            },
        ]
        outcome = await self._follow_prompt(client, pid, prompt, proposals)

        assert outcome.get("success") is True, outcome
        assert sorted(outcome["sections_applied"]) == ["architecture", "description", "tech_stack"]
        stack = await self._read_tech_stack(client, pid)
        assert stack["infrastructure"] == "Reviewed infra"
        assert stack["databases"] == "Reviewed DB"

    async def test_prompt_shows_the_right_value_shape_for_every_section_kind(self, account, db_manager):
        _client, tenant_key = account
        product = await _seed_product(db_manager, tenant_key, "Delta")
        prompt = await _prompt_for(db_manager, tenant_key, str(product.id), ALL_SECTIONS)

        for field in ("programming_languages", "databases_storage", "infrastructure", "primary_pattern", "api_style"):
            assert field in prompt
        assert "tech_stack.infrastructure" in prompt
        assert re.search(r"force\s*=\s*true", prompt, re.IGNORECASE)

    async def test_the_key_get_context_returns_can_be_written_back(self, account, db_manager):
        client, tenant_key = account
        product = await _seed_product(db_manager, tenant_key, "Epsilon")
        pid = str(product.id)
        prompt = await _prompt_for(db_manager, tenant_key, pid, ["tech_stack"])

        stack = await self._read_tech_stack(client, pid)
        assert "databases" in stack
        written_back = {"databases": "Written back under the read name"}
        proposals = [
            {"section": "tech_stack", "drift_detected": True, "proposed_value": written_back},
            {
                "section": "tech_stack.databases",
                "drift_detected": True,
                "proposed_value": "Dotted alias also lands",
            },
        ]
        outcome = await self._follow_prompt(client, pid, prompt, proposals)

        assert outcome.get("success") is True, outcome
        assert "tech_stack.databases" not in outcome.get("sections_skipped", [])
        assert (await self._read_tech_stack(client, pid))["databases"] == "Dotted alias also lands"

    async def test_get_context_still_names_the_field_databases(self, account, db_manager):
        client, tenant_key = account
        product = await _seed_product(db_manager, tenant_key, "Zeta")
        stack = await self._read_tech_stack(client, str(product.id))
        assert stack["databases"] == "ZetaDB"
        assert "databases_storage" not in stack
