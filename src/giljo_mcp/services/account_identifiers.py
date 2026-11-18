# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.exceptions import ValidationError


def require_username_without_at(username: str) -> str:
    if "@" in username:
        raise ValidationError(
            message="Username cannot contain '@'. Put an email address in the email field.",
            error_code="USERNAME_CONTAINS_AT",
            context={"field": "username"},
        )
    return username


def normalize_email(email: str | None) -> str | None:
    return email.strip().lower() if email else email
