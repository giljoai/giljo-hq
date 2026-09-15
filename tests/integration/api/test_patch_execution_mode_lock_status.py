# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.endpoints.projects import router as projects_router
from api.endpoints.projects.dependencies import get_project_service
from api.exception_handlers import register_exception_handlers
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.exceptions import ProjectStateError


pytestmark = pytest.mark.asyncio


_TENANT = "tenant-patch-409-test"


class _FakeUser:
    id = "user-patch-409"
    username = "patch_409_tester"
    tenant_key = _TENANT


class _RaisingProjectService:

    async def update_project(self, project_id: str, updates: dict):
        raise ProjectStateError(
            message=(
                "Cannot change execution mode after implementation has launched. Re-stage the project to change it."
            ),
            context={"project_id": project_id},
        )


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(projects_router)
    register_exception_handlers(app)

    async def _override_user() -> _FakeUser:
        return _FakeUser()

    async def _override_service() -> AsyncIterator[_RaisingProjectService]:
        yield _RaisingProjectService()

    app.dependency_overrides[get_current_active_user] = _override_user
    app.dependency_overrides[get_project_service] = _override_service
    return app


async def test_patch_execution_mode_state_conflict_maps_to_409_not_500():
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            "/api/v1/projects/proj-patch-409",
            json={"execution_mode": "multi_terminal"},
        )

    assert resp.status_code == 409, f"expected 409, got {resp.status_code}: {resp.text}"
    body_text = resp.text.lower()
    assert "launch" in body_text or "implementation" in body_text, (
        f"expected the lock message in the body, got: {resp.text}"
    )
