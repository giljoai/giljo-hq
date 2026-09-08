# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6211c — project-less conductor read-path.

Two strictly-additive fixes that let a PROJECT-LESS chain conductor read context
and learn the protocol etag on its first call:

  Fix 1 (C-3.3): get_context/fetch_context demanded a product_id and errored when
  the caller had neither product_id NOR project_id. The dedicated conductor owns no
  project, so BE-6208e's project_id->product_id resolution can't help. Fall back to
  the session's active product exactly as list_projects does, reusing the existing
  ProductService.get_default_product (no new service, no new table). Additive on the
  previously-erroring path; cross-tenant isolation preserved (ProductService is
  tenant-scoped, ADR-009).

  Fix 2 (S-4a): protocol_etag was emitted ONLY when the caller already passed one,
  so a FIRST (no-etag) get_job_mission never learned it and the ~30KB re-send cache
  stayed inert on the common path. get_agent_mission now ALWAYS emits the etag;
  static-block omission stays gated on a confirmed MATCH only (prose byte-identical).

Parallel-safe (mocked DB, no module-level mutable state). Edition Scope: CE.
"""

from __future__ import annotations

import importlib
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from giljo_mcp.exceptions import ValidationError


# NOTE: ``giljo_mcp.tools.context_tools.__init__`` re-exports the ``fetch_context``
# FUNCTION under the same name as its submodule, so a plain
# ``import ...fetch_context as fc`` binds the function, not the module. Resolve the
# real module via importlib so module-level helpers are patchable.
fc = importlib.import_module("giljo_mcp.tools.context_tools.fetch_context")


# ---------------------------------------------------------------------------
# Fix 1 (C-3.3) — active-product fallback in the read path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_default_product_id_returns_active_product() -> None:
    """The helper reuses ProductService.get_default_product and returns its id."""
    db_manager = MagicMock()
    fake_product = SimpleNamespace(id="prod-6211c")
    with patch("giljo_mcp.services.product_service.ProductService") as svc_cls:
        instance = svc_cls.return_value
        instance.get_default_product = AsyncMock(return_value=fake_product)
        resolved = await fc._resolve_default_product_id("tk_6211c", db_manager)
    assert resolved == "prod-6211c"


@pytest.mark.asyncio
async def test_resolve_default_product_id_raises_when_none() -> None:
    """No active product for the tenant -> ValidationError (not a silent None)."""
    db_manager = MagicMock()
    with patch("giljo_mcp.services.product_service.ProductService") as svc_cls:
        instance = svc_cls.return_value
        instance.get_default_product = AsyncMock(return_value=None)
        with pytest.raises(ValidationError):
            await fc._resolve_default_product_id("tk_6211c", db_manager)


@pytest.mark.asyncio
async def test_fetch_context_no_ids_falls_back_to_active_product(monkeypatch) -> None:
    """With neither product_id nor project_id, fetch_context resolves the active
    product and threads THAT id into category fetching (instead of raising)."""
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
        # Not under test here: the real helper opens its own session via
        # db_manager.get_session_async(), which this bare MagicMock() cannot
        # answer meaningfully.
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
    """Without a db_manager there is nothing to resolve against — the explicit
    'product_id is required' error must still stand (no regression on that path)."""
    with pytest.raises(ValidationError):
        await fc.fetch_context(
            product_id="",
            tenant_key="tk_6211c",
            project_id=None,
            categories=["product_core"],
            db_manager=None,
        )


# ---------------------------------------------------------------------------
# BE-6211g (move c) — project-less conductor identity is role-trimmed end-to-end
# through the _resolve_mission_template wiring (is_chain_conductor -> role).
# ---------------------------------------------------------------------------


async def _resolve_orchestrator_identity(*, is_chain_conductor: bool) -> str:
    """Drive the real MissionService._resolve_mission_template for a PROJECT-LESS,
    no-template orchestrator (the dedicated conductor shape) with the default seed
    (no admin override), returning the composed identity."""
    from giljo_mcp.services.mission_service import MissionService

    svc = MissionService.__new__(MissionService)
    svc._logger = logging.getLogger("test_be6211g")
    svc.db_manager = MagicMock()
    svc._repo = MagicMock()
    svc._repo.get_project_by_id = AsyncMock(return_value=None)  # project-less conductor

    job = SimpleNamespace(job_type="orchestrator", template_id=None, project_id=None, job_id="job-cond-6211g")
    execution = SimpleNamespace(agent_name="orchestrator", agent_display_name="orchestrator")
    prompt_record = SimpleNamespace(is_override=False, content=None)

    with patch("giljo_mcp.system_prompts.service.SystemPromptService") as sp_cls:
        sp_cls.return_value.get_orchestrator_prompt = AsyncMock(return_value=prompt_record)
        # BE-9333 / FE-9408: returns (identity, identity_status, identity_source).
        identity, _status, _source = await svc._resolve_mission_template(
            MagicMock(), job, execution, "tk_6211g", is_chain_conductor=is_chain_conductor
        )
        return identity


@pytest.mark.asyncio
async def test_projectless_conductor_mission_identity_is_trimmed_end_to_end() -> None:
    """is_chain_conductor=True threads role='conductor' into compose, so the
    conductor's resolved identity drops the three conductor-irrelevant seed blocks."""
    cond = await _resolve_orchestrator_identity(is_chain_conductor=True)
    assert "## Before Closeout" not in cond
    assert "### RESPONDING TO CONTEXT REQUESTS" not in cond
    assert "- `spawn_job`:" not in cond
    # The coordination principles END anchor + the harness are retained.
    assert "## ORCHESTRATOR COORDINATION PRINCIPLES" in cond


@pytest.mark.asyncio
async def test_non_conductor_orchestrator_identity_is_byte_identical_to_solo() -> None:
    """is_chain_conductor=False (solo / sub-orch) yields role=None -> the resolved
    identity is byte-identical to today's default composed solo identity.

    FE-9408 appends one provenance line to the served text, so the equality is stated
    against the composition and that delta. Splitting on the delta keeps this exactly
    as strict about the composed BYTES as it was -- which is the whole point of the
    test -- rather than relaxing it to a substring check.
    """
    from giljo_mcp.template_seeder import compose_orchestrator_identity

    resolved = await _resolve_orchestrator_identity(is_chain_conductor=False)
    composed, _, source_line = resolved.rpartition("\n\n")
    assert composed == compose_orchestrator_identity(None, tool="multi_terminal")
    assert source_line == "identity source: built-in default"
    assert "## Before Closeout" in resolved, "the full solo seed must be retained for a non-conductor"


def test_compute_is_chain_conductor_truth_table() -> None:
    """BE-6211g: the SHARED conductor-signal helper used by BOTH the identity trim
    (mission_service) and the protocol-body trim (mission_assembly), so the two can
    never disagree on conductor-ness for one run (the prior duplicated inline literal)."""
    from giljo_mcp.services.mission_assembly import compute_is_chain_conductor

    assert compute_is_chain_conductor("multi_terminal", None) is True  # active run + no project = conductor
    assert compute_is_chain_conductor("claude_code_cli", "p1") is False  # sub-orch (owns a project)
    assert compute_is_chain_conductor(None, None) is False  # solo (no active chain run)
    assert compute_is_chain_conductor("", None) is False  # empty mode = no run
