# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import importlib
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from giljo_mcp.exceptions import ValidationError


fc = importlib.import_module("giljo_mcp.tools.context_tools.fetch_context")




@pytest.mark.asyncio
async def test_resolve_default_product_id_returns_active_product() -> None:
    db_manager = MagicMock()
    fake_product = SimpleNamespace(id="prod-6211c")
    with patch("giljo_mcp.services.product_service.ProductService") as svc_cls:
        instance = svc_cls.return_value
        instance.get_default_product = AsyncMock(return_value=fake_product)
        resolved = await fc._resolve_default_product_id("tk_6211c", db_manager)
    assert resolved == "prod-6211c"


@pytest.mark.asyncio
async def test_resolve_default_product_id_raises_when_none() -> None:
    db_manager = MagicMock()
    with patch("giljo_mcp.services.product_service.ProductService") as svc_cls:
        instance = svc_cls.return_value
        instance.get_default_product = AsyncMock(return_value=None)
        with pytest.raises(ValidationError):
            await fc._resolve_default_product_id("tk_6211c", db_manager)


@pytest.mark.asyncio
async def test_fetch_context_no_ids_falls_back_to_active_product(monkeypatch) -> None:
    db_manager = MagicMock()
    seen: dict[str, str] = {}

    async def _fake_resolve(tenant_key, dbm):  # noqa: ANN001
        return "prod-active"

    async def _fake_enabled(category, tenant_key, dbm):  # noqa: ANN001
        return True

    async def _fake_depths(tenant_key, dbm):  # noqa: ANN001
        return {}

    async def _fake_fetch_category(*, product_id, **kwargs):  # noqa: ANN001, ANN003
        seen["product_id"] = product_id
        return {"data": {}, "directives": {}}

    async def _fake_last_modified(product_id, tenant_key, dbm):  # noqa: ANN001
        return {}

    monkeypatch.setattr(fc, "_resolve_default_product_id", _fake_resolve)
    monkeypatch.setattr(fc, "_is_category_enabled", _fake_enabled)
    monkeypatch.setattr(fc, "_load_user_depth_config", _fake_depths)
    monkeypatch.setattr(fc, "_fetch_category", _fake_fetch_category)
    monkeypatch.setattr(fc, "_build_last_modified_map", _fake_last_modified)

    result = await fc.fetch_context(
        product_id="",
        tenant_key="tk_6211c",
        project_id=None,
        categories=["product_core"],
        db_manager=db_manager,
    )

    assert seen.get("product_id") == "prod-active", "active product id must be threaded into the fetch"
    assert "error" not in result, f"must not error on the project-less path: {result.get('error')}"


@pytest.mark.asyncio
async def test_fetch_context_no_ids_no_db_still_errors() -> None:
    with pytest.raises(ValidationError):
        await fc.fetch_context(
            product_id="",
            tenant_key="tk_6211c",
            project_id=None,
            categories=["product_core"],
            db_manager=None,
        )




async def _resolve_orchestrator_identity(*, is_chain_conductor: bool) -> str:
    from giljo_mcp.services.mission_service import MissionService

    svc = MissionService.__new__(MissionService)
    svc._logger = logging.getLogger("test_be6211g")
    svc.db_manager = MagicMock()
    svc._repo = MagicMock()
    svc._repo.get_project_by_id = AsyncMock(return_value=None)

    job = SimpleNamespace(job_type="orchestrator", template_id=None, project_id=None, job_id="job-cond-6211g")
    execution = SimpleNamespace(agent_name="orchestrator", agent_display_name="orchestrator")
    prompt_record = SimpleNamespace(is_override=False, content=None)

    with patch("giljo_mcp.system_prompts.service.SystemPromptService") as sp_cls:
        sp_cls.return_value.get_orchestrator_prompt = AsyncMock(return_value=prompt_record)
        identity, _status, _source, _template = await svc._resolve_mission_template(
            MagicMock(), job, execution, "tk_6211g", is_chain_conductor=is_chain_conductor
        )
        return identity


@pytest.mark.asyncio
async def test_projectless_conductor_mission_identity_is_trimmed_end_to_end() -> None:
    cond = await _resolve_orchestrator_identity(is_chain_conductor=True)
    assert "## Before Closeout" not in cond
    assert "### RESPONDING TO CONTEXT REQUESTS" not in cond
    assert "- `spawn_job`:" not in cond
    assert "## ORCHESTRATOR COORDINATION PRINCIPLES" in cond


@pytest.mark.asyncio
async def test_non_conductor_orchestrator_identity_is_byte_identical_to_solo() -> None:
    from giljo_mcp.template_seeder import compose_orchestrator_identity

    resolved = await _resolve_orchestrator_identity(is_chain_conductor=False)
    composed, _, source_line = resolved.rpartition("\n\n")
    assert composed == compose_orchestrator_identity(None, tool="multi_terminal")
    assert source_line == "identity source: built-in default"
    assert "## Before Closeout" in resolved, "the full solo seed must be retained for a non-conductor"


def test_compute_is_chain_conductor_truth_table() -> None:
    from giljo_mcp.services.mission_assembly import compute_is_chain_conductor

    assert compute_is_chain_conductor("multi_terminal", None) is True
    assert compute_is_chain_conductor("claude_code_cli", "p1") is False
    assert compute_is_chain_conductor(None, None) is False
    assert compute_is_chain_conductor("", None) is False
