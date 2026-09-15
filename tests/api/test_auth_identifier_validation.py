# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.endpoints.auth import LoginRequest
from api.endpoints.auth_models import CheckFirstLoginRequest, PinPasswordResetRequest


def _email_with_length(length: int) -> str:
    domain = "@example.com"
    return f"{'a' * (length - len(domain))}{domain}"


def test_login_request_accepts_email_identifier_longer_than_username_limit() -> None:
    identifier = _email_with_length(120)

    request = LoginRequest(username=identifier, password="Password123!")

    assert request.username == identifier


def test_first_login_request_accepts_email_identifier_longer_than_username_limit() -> None:
    identifier = _email_with_length(120)

    request = CheckFirstLoginRequest(username=identifier)

    assert request.username == identifier


def test_pin_reset_request_accepts_email_identifier_longer_than_username_limit() -> None:
    identifier = _email_with_length(120)

    request = PinPasswordResetRequest(
        username=identifier,
        recovery_pin="1234",
        new_password="Password123!",
        confirm_password="Password123!",
    )

    assert request.username == identifier


@pytest.mark.parametrize(
    "model,payload",
    [
        (LoginRequest, {"password": "Password123!"}),
        (CheckFirstLoginRequest, {}),
        (
            PinPasswordResetRequest,
            {"recovery_pin": "1234", "new_password": "Password123!", "confirm_password": "Password123!"},
        ),
    ],
)
def test_auth_identifier_still_rejects_values_above_email_safe_limit(model, payload) -> None:
    with pytest.raises(ValidationError):
        model(username=_email_with_length(256), **payload)
