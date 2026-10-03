# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/serena/settings", "/api/serena/status"])
async def test_serena_get_routes_return_404(api_client, auth_headers, path):
    response = await api_client.get(path, headers=auth_headers)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_serena_toggle_answers_like_a_path_that_never_existed(api_client, auth_headers):
    body = {"use_in_prompts": True}
    never_existed = await api_client.post("/api/never-existed/toggle", headers=auth_headers, json=body)

    response = await api_client.post("/api/serena/toggle", headers=auth_headers, json=body)

    assert never_existed.status_code in (404, 405)
    assert response.status_code == never_existed.status_code
