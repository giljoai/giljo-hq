# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from api.endpoints import configuration, downloads
from giljo_mcp.auth.dependencies import get_current_active_user, require_admin, require_ce_mode


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(configuration.router, prefix="/api/v1/config")
    app.dependency_overrides[get_current_active_user] = object
    app.dependency_overrides[require_admin] = object
    app.dependency_overrides[require_ce_mode] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_database_config_is_the_live_connection(client, monkeypatch):
    from api.app_state import state

    prior = state.db_manager
    state.db_manager = SimpleNamespace(database_url="postgresql://live_user:s3cret@db.example.test:6543/live_db")
    try:
        body = client.get("/api/v1/config/database").json()
    finally:
        state.db_manager = prior
    assert body == {
        "host": "db.example.test",
        "port": 6543,
        "name": "live_db",
        "user": "live_user",
        "password_masked": "******",
    }


def test_database_config_is_503_when_no_database_is_connected(client):
    from api.app_state import state

    prior = state.db_manager
    state.db_manager = None
    try:
        response = client.get("/api/v1/config/database")
    finally:
        state.db_manager = prior
    assert response.status_code == 503


def test_slash_commands_zip_refuses_a_missing_install_script(monkeypatch, tmp_path):
    from api.endpoints.downloads import bundles

    monkeypatch.setattr(bundles, "INSTALL_SCRIPT_TEMPLATES_DIR", tmp_path)
    app = FastAPI()
    app.include_router(downloads.router)
    response = TestClient(app, raise_server_exceptions=False).get("/api/download/slash-commands.zip")
    assert response.status_code == 500, response.text
