# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from giljo_mcp.services.memory_entry_write_validator import (
    CONTROLLED_TAG_VOCABULARY,
    MemoryEntryWriteValidationError,
)
from giljo_mcp.tools.project_closeout import close_project_and_update_memory
from tests.helpers.model_factories import make_product, make_project


def _build_session_mocks(tenant_key: str):
    project_id = str(uuid4())
    product_id = str(uuid4())

    mock_project = make_project(
        id=project_id,
        tenant_key=tenant_key,
        product_id=product_id,
        created_at=datetime.now(UTC),
        name="Tags Param Test Project",
    )

    mock_product = make_product(id=product_id, tenant_key=tenant_key, product_memory={})

    mock_session = AsyncMock()
    mock_session.info = {}
    mock_db_manager = MagicMock()
    mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

    call_count = {"n": 0}

    async def mock_execute(*_args, **_kwargs):
        call_count["n"] += 1
        result = MagicMock()
        if call_count["n"] == 1:
            result.scalar_one_or_none.return_value = mock_project
        elif call_count["n"] == 2:
            result.scalar_one_or_none.return_value = mock_product
        else:
            scalars = MagicMock()
            scalars.all.return_value = []
            result.scalars.return_value = scalars
        return result

    mock_session.execute = AsyncMock(side_effect=mock_execute)
    return mock_session, mock_db_manager, mock_project, mock_product, project_id


async def _run_closeout(
    *,
    project_id: str,
    db_manager,
    tenant_key: str,
    tags,
    captured: dict,
):
    mock_entry = MagicMock()
    mock_entry.id = str(uuid4())
    mock_entry.to_dict.return_value = {"id": str(mock_entry.id)}

    async def _capture_create(params, session):
        captured["params"] = params
        return mock_entry

    with patch("giljo_mcp.tools.project_closeout.ProductMemoryService") as mock_svc_cls:
        svc = mock_svc_cls.return_value
        svc.get_next_sequence = AsyncMock(return_value=1)
        svc.get_closeout_entry_for_project = AsyncMock(return_value=None)
        svc.create_entry = AsyncMock(side_effect=_capture_create)

        with patch(
            "giljo_mcp.tools.project_closeout.emit_websocket_event",
            new_callable=AsyncMock,
        ):
            return await close_project_and_update_memory(
                project_id=project_id,
                summary="BE-5032 closeout summary",
                key_outcomes=["outcome-1"],
                decisions_made=["decision-1"],
                tags=tags,
                tenant_key=tenant_key,
                db_manager=db_manager,
                force=False,
                git_commits=[],
            )


@pytest.mark.asyncio
async def test_close_with_valid_tags_persists_exact_tags():
    tenant_key = "test-tenant"
    _, db_manager, _, _, project_id = _build_session_mocks(tenant_key)
    captured: dict = {}

    result = await _run_closeout(
        project_id=project_id,
        db_manager=db_manager,
        tenant_key=tenant_key,
        tags=["refactor", "backend"],
        captured=captured,
    )

    assert "entry_id" in result
    params = captured["params"]
    assert params.tags == ["refactor", "backend"]


@pytest.mark.asyncio
async def test_close_with_invalid_tag_raises_structured_error():
    tenant_key = "test-tenant"
    _, db_manager, _, _, project_id = _build_session_mocks(tenant_key)
    captured: dict = {}

    with pytest.raises(MemoryEntryWriteValidationError) as exc_info:
        await _run_closeout(
            project_id=project_id,
            db_manager=db_manager,
            tenant_key=tenant_key,
            tags=["frobnicate"],
            captured=captured,
        )

    err = exc_info.value
    assert err.field == "tags"
    assert err.invalid_tag == "frobnicate"
    assert err.allowed == sorted(CONTROLLED_TAG_VOCABULARY)
    assert "params" not in captured


@pytest.mark.asyncio
async def test_close_with_none_tags_persists_empty():
    tenant_key = "test-tenant"
    _, db_manager, _, _, project_id = _build_session_mocks(tenant_key)
    captured: dict = {}

    await _run_closeout(
        project_id=project_id,
        db_manager=db_manager,
        tenant_key=tenant_key,
        tags=None,
        captured=captured,
    )

    assert captured["params"].tags == []


@pytest.mark.asyncio
async def test_close_with_empty_tags_persists_empty():
    tenant_key = "test-tenant"
    _, db_manager, _, _, project_id = _build_session_mocks(tenant_key)
    captured: dict = {}

    await _run_closeout(
        project_id=project_id,
        db_manager=db_manager,
        tenant_key=tenant_key,
        tags=[],
        captured=captured,
    )

    assert captured["params"].tags == []


@pytest.mark.asyncio
async def test_close_with_mixed_valid_invalid_rejects_all():
    tenant_key = "test-tenant"
    _, db_manager, _, _, project_id = _build_session_mocks(tenant_key)
    captured: dict = {}

    with pytest.raises(MemoryEntryWriteValidationError) as exc_info:
        await _run_closeout(
            project_id=project_id,
            db_manager=db_manager,
            tenant_key=tenant_key,
            tags=["refactor", "junk"],
            captured=captured,
        )

    assert exc_info.value.invalid_tag == "junk"
    assert "params" not in captured


def test_extract_tags_function_is_deleted():
    import giljo_mcp.tools.project_closeout as mod

    assert not hasattr(mod, "_extract_tags"), (
        "BE-5032: _extract_tags() word-splitter must be removed; agent-supplied tags only."
    )
