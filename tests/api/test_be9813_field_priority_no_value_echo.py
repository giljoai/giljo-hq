# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest


MARKER = "be9813-fp-marker"


def _assert_refused_without_echo(resp) -> None:
    assert resp.status_code == 422, resp.text
    assert MARKER not in resp.text, resp.text
    (entry,) = resp.json()["errors"]
    assert entry["loc"] == ["body", "priorities"]


@pytest.mark.asyncio
async def test_unknown_category_name_is_not_echoed(api_client, auth_headers):
    resp = await api_client.put(
        "/api/v1/users/me/field-priority",
        headers=auth_headers,
        json={"priorities": {MARKER: True, "tech_stack": True}},
    )
    _assert_refused_without_echo(resp)
    assert "Valid categories" in resp.json()["errors"][0]["msg"]


@pytest.mark.asyncio
async def test_non_boolean_toggle_value_is_not_echoed(api_client, auth_headers):
    resp = await api_client.put(
        "/api/v1/users/me/field-priority",
        headers=auth_headers,
        json={"priorities": {"tech_stack": MARKER}},
    )
    _assert_refused_without_echo(resp)
    assert "tech_stack" in resp.json()["errors"][0]["msg"]
