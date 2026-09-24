# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from giljo_mcp.models import Project
from giljo_mcp.models.auth import User
from giljo_mcp.tools.write_memory_entry import write_360_memory


@pytest_asyncio.fixture
async def linked_project(db_session, test_tenant_key, test_product):
    project = Project(
        id=str(uuid.uuid4()),
        name="IMP-5037 Boundary Test Project",
        description="Project for write_360_memory boundary tests",
        mission="Test mission",
        status="active",
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    return project


@pytest_asyncio.fixture
async def opt_in_user(db_session, test_tenant_key):
    user = User(
        id=str(uuid.uuid4()),
        username=f"opt-in-{uuid.uuid4().hex[:8]}",
        email=f"opt-in-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        tenant_key=test_tenant_key,
        is_active=True,
        role="developer",
        notification_preferences={
            "context_tuning_reminder": True,
            "tuning_reminder_threshold": 3,
        },
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_write_360_memory_passes_real_user_id_to_staleness_check(
    db_session, test_tenant_key, test_product, linked_project, opt_in_user
):
    mock_db_manager = MagicMock()
    captured_user_ids: list[str] = []

    async def _spy_check(self, product_id, user_id):
        captured_user_ids.append(user_id)
        return {"is_stale": False, "projects_since_tune": 0, "threshold": 3, "enabled": True}

    with patch(
        "giljo_mcp.services.product_tuning_service.ProductTuningService.check_tuning_staleness",
        new=_spy_check,
    ):
        await write_360_memory(
            project_id=str(linked_project.id),
            tenant_key=test_tenant_key,
            summary="Closeout passing explicit user_id",
            key_outcomes=["Outcome A"],
            decisions_made=["Decision A"],
            entry_type="decision",
            db_manager=mock_db_manager,
            session=db_session,
            user_id=str(opt_in_user.id),
        )

    assert captured_user_ids == [str(opt_in_user.id)], (
        f"Expected check_tuning_staleness to receive the explicit user_id "
        f"{opt_in_user.id!r}, but got {captured_user_ids!r}. With the pre-fix code "
        f"this list would contain the tenant_key {test_tenant_key!r}."
    )


@pytest.mark.asyncio
async def test_write_360_memory_resolves_tenant_user_when_user_id_omitted(
    db_session, test_tenant_key, test_product, linked_project, opt_in_user
):
    mock_db_manager = MagicMock()
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _yield_db_session():
        yield db_session

    mock_db_manager.get_session_async = MagicMock(side_effect=_yield_db_session)

    captured_user_ids: list[str] = []

    async def _spy_check(self, product_id, user_id):
        captured_user_ids.append(user_id)
        return {"is_stale": False, "projects_since_tune": 0, "threshold": 3, "enabled": True}

    with patch(
        "giljo_mcp.services.product_tuning_service.ProductTuningService.check_tuning_staleness",
        new=_spy_check,
    ):
        await write_360_memory(
            project_id=str(linked_project.id),
            tenant_key=test_tenant_key,
            summary="Closeout with user_id resolved from tenant",
            key_outcomes=["Outcome A"],
            decisions_made=["Decision A"],
            entry_type="decision",
            db_manager=mock_db_manager,
            session=db_session,
        )

    assert captured_user_ids == [str(opt_in_user.id)], (
        f"Expected the tenant-resolver fallback to pass the active user {opt_in_user.id!r}, got {captured_user_ids!r}."
    )


@pytest.mark.asyncio
async def test_write_360_memory_emits_notification_when_threshold_exceeded(
    db_session, test_tenant_key, test_product, linked_project, opt_in_user
):
    mock_db_manager = MagicMock()
    captured_events: list[dict] = []

    async def _stale_check(self, product_id, user_id):
        return {"is_stale": True, "projects_since_tune": 5, "threshold": 3, "enabled": True}

    async def _capture_emit(*, event_type, tenant_key, product_id, data):
        captured_events.append(
            {"event_type": event_type, "tenant_key": tenant_key, "product_id": product_id, "data": data}
        )

    with (
        patch(
            "giljo_mcp.services.product_tuning_service.ProductTuningService.check_tuning_staleness",
            new=_stale_check,
        ),
        patch("giljo_mcp.tools.write_memory_entry.emit_websocket_event", new=AsyncMock(side_effect=_capture_emit)),
    ):
        await write_360_memory(
            project_id=str(linked_project.id),
            tenant_key=test_tenant_key,
            summary="Closeout that should emit tuning reminder",
            key_outcomes=["Outcome A"],
            decisions_made=["Decision A"],
            entry_type="decision",
            db_manager=mock_db_manager,
            session=db_session,
            user_id=str(opt_in_user.id),
        )

    tuning_events = [
        e
        for e in captured_events
        if e["event_type"] == "notification:new" and e["data"].get("type") == "context_tuning"
    ]
    assert len(tuning_events) == 1, (
        f"Expected exactly one context_tuning notification when is_stale=True, got: {tuning_events}"
    )
    assert tuning_events[0]["tenant_key"] == test_tenant_key
    assert tuning_events[0]["data"]["metadata"]["product_id"] == str(test_product.id)
