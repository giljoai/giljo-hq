# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from httpx import AsyncClient

from giljo_mcp.domain.task_status import TASK_STATUS_META, TaskStatus


_EXPECTED_VALUES = [s.value for s in TaskStatus]


@pytest.mark.asyncio
async def test_list_task_statuses_returns_six_canonical_members(api_client: AsyncClient, auth_headers: dict) -> None:
    resp = await api_client.get("/api/v1/task-statuses/", headers=auth_headers)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert isinstance(body, list)
    assert [item["value"] for item in body] == _EXPECTED_VALUES


@pytest.mark.asyncio
async def test_list_task_statuses_payload_shape(api_client: AsyncClient, auth_headers: dict) -> None:
    resp = await api_client.get("/api/v1/task-statuses/", headers=auth_headers)
    assert resp.status_code == 200

    for item in resp.json():
        assert set(item.keys()) == {
            "value",
            "label",
            "color_token",
            "is_lifecycle_finished",
        }
        assert isinstance(item["value"], str)
        assert isinstance(item["label"], str)
        assert isinstance(item["color_token"], str)
        assert isinstance(item["is_lifecycle_finished"], bool)
        assert not item["color_token"].startswith("#")


@pytest.mark.asyncio
async def test_list_task_statuses_metadata_matches_domain(api_client: AsyncClient, auth_headers: dict) -> None:
    resp = await api_client.get("/api/v1/task-statuses/", headers=auth_headers)
    assert resp.status_code == 200

    by_value = {item["value"]: item for item in resp.json()}
    for member, meta in TASK_STATUS_META.items():
        item = by_value[member.value]
        assert item["label"] == meta.label
        assert item["color_token"] == meta.color_token
        assert item["is_lifecycle_finished"] is meta.is_lifecycle_finished


@pytest.mark.asyncio
async def test_list_task_statuses_requires_auth(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/task-statuses/")
    assert resp.status_code == 401, resp.text
