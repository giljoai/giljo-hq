# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest


PASSWORD_73_BYTES = "Sec9811!" + "q" * 65
BAD_PIN = "73195"
NOT_A_LIST_MARKER = "sec9811-not-a-list-marker"


class _NoopRateLimiter:
    async def check_rate_limit(self, *args, **kwargs):
        return None


def _assert_no_echo(resp, *secrets_sent: str) -> None:
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["message"] == "Request validation failed"
    assert body["errors"], body
    for entry in body["errors"]:
        assert set(entry) == {"loc", "msg", "type"}, entry
    for secret in secrets_sent:
        assert secret not in resp.text


def test_password_constant_is_73_bytes():
    assert len(PASSWORD_73_BYTES.encode("utf-8")) == 73


@pytest.mark.asyncio
async def test_refused_password_is_not_echoed(api_client, monkeypatch):
    monkeypatch.setattr("api.endpoints.auth_pin_recovery.GILJO_MODE", "")
    monkeypatch.setattr("api.endpoints.auth_pin_recovery.get_rate_limiter", _NoopRateLimiter)

    resp = await api_client.post(
        "/api/auth/verify-pin-and-reset-password",
        json={
            "username": f"sec9811_{uuid4().hex[:8]}",
            "recovery_pin": "4242",
            "new_password": PASSWORD_73_BYTES,
            "confirm_password": PASSWORD_73_BYTES,
        },
    )
    _assert_no_echo(resp, PASSWORD_73_BYTES)
    assert {entry["loc"][-1] for entry in resp.json()["errors"]} == {"new_password", "confirm_password"}


@pytest.mark.asyncio
async def test_refused_recovery_pin_is_not_echoed(api_client, monkeypatch):
    monkeypatch.setattr("api.endpoints.auth_pin_recovery.GILJO_MODE", "")
    monkeypatch.setattr("api.endpoints.auth_pin_recovery.get_rate_limiter", _NoopRateLimiter)

    resp = await api_client.post(
        "/api/auth/verify-pin-and-reset-password",
        json={
            "username": f"sec9811_{uuid4().hex[:8]}",
            "recovery_pin": BAD_PIN,
            "new_password": "GoodPass1!",
            "confirm_password": "GoodPass1!",
        },
    )
    _assert_no_echo(resp, BAD_PIN)
    assert [entry["loc"] for entry in resp.json()["errors"]] == [["body", "recovery_pin"]]


@pytest.mark.asyncio
async def test_malformed_non_secret_field_keeps_loc_msg_type_without_input(api_client, auth_headers):
    resp = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": f"sec9811 {uuid4().hex[:8]}", "target_platforms": NOT_A_LIST_MARKER},
    )
    _assert_no_echo(resp, NOT_A_LIST_MARKER)
    (entry,) = resp.json()["errors"]
    assert entry["loc"] == ["body", "target_platforms"]
    assert entry["type"] == "list_type"
    assert entry["msg"]
