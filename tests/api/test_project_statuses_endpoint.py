# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from httpx import AsyncClient

from giljo_mcp.domain.project_status import PROJECT_STATUS_META, ProjectStatus


_EXPECTED_VALUES = [s.value for s in ProjectStatus]


@pytest.mark.asyncio
async def test_list_project_statuses_returns_canonical_members(api_client: AsyncClient, auth_headers: dict) -> None:

    resp = await api_client.get("/api/v1/project-statuses/", headers=auth_headers)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert isinstance(body, list)
    assert [item["value"] for item in body] == _EXPECTED_VALUES


@pytest.mark.asyncio
async def test_list_project_statuses_payload_shape(api_client: AsyncClient, auth_headers: dict) -> None:

    resp = await api_client.get("/api/v1/project-statuses/", headers=auth_headers)
    assert resp.status_code == 200

    for item in resp.json():
        assert set(item.keys()) == {
            "value",
            "label",
            "color_token",
            "is_lifecycle_finished",
            "is_immutable",
            "is_user_mutable_via_mcp",
        }
        assert isinstance(item["value"], str)
        assert isinstance(item["label"], str)
        assert isinstance(item["color_token"], str)
        assert isinstance(item["is_lifecycle_finished"], bool)
        assert isinstance(item["is_immutable"], bool)
        assert isinstance(item["is_user_mutable_via_mcp"], bool)
        assert not item["color_token"].startswith("#")


@pytest.mark.asyncio
async def test_list_project_statuses_metadata_matches_domain(api_client: AsyncClient, auth_headers: dict) -> None:

    resp = await api_client.get("/api/v1/project-statuses/", headers=auth_headers)
    assert resp.status_code == 200

    by_value = {item["value"]: item for item in resp.json()}
    for member, meta in PROJECT_STATUS_META.items():
        item = by_value[member.value]
        assert item["label"] == meta.label
        assert item["color_token"] == meta.color_token
        assert item["is_lifecycle_finished"] is meta.is_lifecycle_finished
        assert item["is_immutable"] is meta.is_immutable
        assert item["is_user_mutable_via_mcp"] is meta.is_user_mutable_via_mcp


@pytest.mark.asyncio
async def test_list_project_statuses_requires_auth(api_client: AsyncClient) -> None:

    resp = await api_client.get("/api/v1/project-statuses/")
    assert resp.status_code == 401, resp.text


_GRANDFATHERED_COLOR_COLLISIONS: frozenset[frozenset[str]] = frozenset(
    {frozenset({ProjectStatus.TERMINATED.value, ProjectStatus.DELETED.value})}
)


def test_no_unexpected_color_token_collisions_across_statuses() -> None:

    by_token: dict[str, list[str]] = {}
    for status, meta in PROJECT_STATUS_META.items():
        by_token.setdefault(meta.color_token, []).append(status.value)

    for token, statuses in by_token.items():
        if len(statuses) < 2:
            continue
        pair = frozenset(statuses)
        assert pair in _GRANDFATHERED_COLOR_COLLISIONS, (
            f"Unexpected color_token collision on '{token}': {sorted(statuses)}. "
            "Either assign a distinct token or add an explicit grandfather entry "
            "with a comment explaining why the collision is acceptable."
        )
