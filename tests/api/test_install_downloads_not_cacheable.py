# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.endpoints import downloads


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(downloads.router)
    return TestClient(app, base_url="http://lan-host.example:7272")


@pytest.mark.parametrize(
    "path",
    [
        "/api/download/slash-commands.zip",
        "/api/download/install-script.sh?script_type=slash-commands",
        "/api/download/install-script.ps1?script_type=slash-commands",
    ],
)
def test_host_embedding_download_is_not_stored_by_caches(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    cache_control = response.headers.get("cache-control", "")
    assert "no-store" in cache_control, f"{path} embeds the request host but sends Cache-Control={cache_control!r}"


def test_install_script_still_embeds_the_request_host(client: TestClient) -> None:
    response = client.get("/api/download/install-script.sh?script_type=slash-commands")

    assert "http://lan-host.example:7272" in response.text
