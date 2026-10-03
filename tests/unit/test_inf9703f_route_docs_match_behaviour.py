# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


from __future__ import annotations

from fastapi import FastAPI

from api.endpoints.tasks import router as tasks_router
from api.endpoints.users import router as users_router


def _description(router, path: str, method: str) -> str:
    app = FastAPI()
    app.include_router(router)
    return app.openapi()["paths"][path][method]["description"]


def test_task_update_description_names_admin_or_creator_only():
    text = _description(tasks_router, "/{task_id}", "patch")
    assert "assigned to them" not in text
    assert "creator" in text
    assert "admin" in text.lower()


def test_get_user_description_is_scoped_to_the_callers_tenant():
    text = _description(users_router, "/{user_id}", "get")
    assert "across all tenants" not in text
    assert "own tenant" in text
