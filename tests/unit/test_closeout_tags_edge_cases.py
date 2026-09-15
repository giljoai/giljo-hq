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
    MEMORY_TAGS_COUNT,
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
        name="BE-5032 edge-case project",
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
    return mock_session, mock_db_manager, project_id


async def _run_closeout(*, project_id, db_manager, tenant_key, tags, captured):
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
                summary="Edge-case closeout",
                key_outcomes=["outcome"],
                decisions_made=["decision"],
                tags=tags,
                tenant_key=tenant_key,
                db_manager=db_manager,
                force=False,
                git_commits=[],
            )




@pytest.mark.parametrize("tag", sorted(CONTROLLED_TAG_VOCABULARY))
@pytest.mark.asyncio
async def test_every_controlled_vocab_tag_is_accepted(tag):
    tenant_key = "test-tenant"
    _, db_manager, project_id = _build_session_mocks(tenant_key)
    captured: dict = {}

    await _run_closeout(
        project_id=project_id,
        db_manager=db_manager,
        tenant_key=tenant_key,
        tags=[tag],
        captured=captured,
    )

    assert captured["params"].tags == [tag]




@pytest.mark.asyncio
async def test_tags_at_cap_are_accepted():
    tenant_key = "test-tenant"
    _, db_manager, project_id = _build_session_mocks(tenant_key)
    captured: dict = {}

    eight = sorted(CONTROLLED_TAG_VOCABULARY)[:MEMORY_TAGS_COUNT]
    assert len(eight) == MEMORY_TAGS_COUNT

    await _run_closeout(
        project_id=project_id,
        db_manager=db_manager,
        tenant_key=tenant_key,
        tags=eight,
        captured=captured,
    )

    assert captured["params"].tags == eight


@pytest.mark.asyncio
async def test_tags_over_cap_are_rejected():
    tenant_key = "test-tenant"
    _, db_manager, project_id = _build_session_mocks(tenant_key)
    captured: dict = {}

    nine = sorted(CONTROLLED_TAG_VOCABULARY)[: MEMORY_TAGS_COUNT + 1]
    assert len(nine) == MEMORY_TAGS_COUNT + 1

    with pytest.raises(MemoryEntryWriteValidationError) as exc_info:
        await _run_closeout(
            project_id=project_id,
            db_manager=db_manager,
            tenant_key=tenant_key,
            tags=nine,
            captured=captured,
        )

    assert exc_info.value.field == "tags"
    assert "params" not in captured




@pytest.mark.asyncio
async def test_duplicate_tags_persist_verbatim():
    tenant_key = "test-tenant"
    _, db_manager, project_id = _build_session_mocks(tenant_key)
    captured: dict = {}

    await _run_closeout(
        project_id=project_id,
        db_manager=db_manager,
        tenant_key=tenant_key,
        tags=["refactor", "refactor"],
        captured=captured,
    )

    assert captured["params"].tags == ["refactor", "refactor"]




@pytest.mark.asyncio
async def test_whitespace_padded_tags_are_rejected():
    tenant_key = "test-tenant"
    _, db_manager, project_id = _build_session_mocks(tenant_key)
    captured: dict = {}

    with pytest.raises(MemoryEntryWriteValidationError) as exc_info:
        await _run_closeout(
            project_id=project_id,
            db_manager=db_manager,
            tenant_key=tenant_key,
            tags=["  refactor  "],
            captured=captured,
        )

    assert exc_info.value.field == "tags"
    assert exc_info.value.invalid_tag == "  refactor  "
    assert "params" not in captured




@pytest.mark.asyncio
async def test_tool_accessor_threads_tags_through_to_tool_function():
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    accessor = ToolAccessor.__new__(ToolAccessor)
    accessor.db_manager = MagicMock()
    accessor._websocket_manager = None

    captured_kwargs: dict = {}

    async def fake_tool_func(**kwargs):
        captured_kwargs.update(kwargs)
        return {"ok": True}

    with patch(
        "giljo_mcp.tools.project_closeout.close_project_and_update_memory",
        new=fake_tool_func,
    ):
        result = await accessor.write_project_closeout(
            project_id="proj-1",
            summary="boundary test",
            key_outcomes=["a"],
            decisions_made=["b"],
            tenant_key="test-tenant",
            tags=["refactor", "backend"],
        )

    assert result == {"ok": True}
    assert captured_kwargs["tags"] == ["refactor", "backend"]
    assert captured_kwargs["tenant_key"] == "test-tenant"
    assert "db_manager" in captured_kwargs


@pytest.mark.asyncio
async def test_tool_accessor_passes_none_tags_through():
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    accessor = ToolAccessor.__new__(ToolAccessor)
    accessor.db_manager = MagicMock()
    accessor._websocket_manager = None

    captured_kwargs: dict = {}

    async def fake_tool_func(**kwargs):
        captured_kwargs.update(kwargs)
        return {"ok": True}

    with patch(
        "giljo_mcp.tools.project_closeout.close_project_and_update_memory",
        new=fake_tool_func,
    ):
        await accessor.write_project_closeout(
            project_id="proj-1",
            summary="boundary test",
            key_outcomes=["a"],
            decisions_made=["b"],
            tenant_key="test-tenant",
        )

    assert captured_kwargs["tags"] is None




@pytest.mark.asyncio
async def test_closeout_succeeds_without_deliverables():
    tenant_key = "test-tenant"
    _, db_manager, project_id = _build_session_mocks(tenant_key)
    captured: dict = {}

    await _run_closeout(
        project_id=project_id,
        db_manager=db_manager,
        tenant_key=tenant_key,
        tags=["refactor"],
        captured=captured,
    )

    assert captured["params"].deliverables is None
