# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, field_validator

from giljo_mcp.utils.password_helper import BCRYPT_MAX_PASSWORD_BYTES


def validate_password_byte_length(v: str) -> str:
    if len(v.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes when encoded as UTF-8")
    return v


BoundedPassword = Annotated[
    str,
    StringConstraints(min_length=8, max_length=BCRYPT_MAX_PASSWORD_BYTES),
    AfterValidator(validate_password_byte_length),
]


def validate_password_strength(v: str) -> str:
    validate_password_byte_length(v)
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not any(c.isupper() for c in v):
        raise ValueError("Password must contain at least 1 uppercase letter")
    if not any(c.islower() for c in v):
        raise ValueError("Password must contain at least 1 lowercase letter")
    if not any(c.isdigit() for c in v):
        raise ValueError("Password must contain at least 1 number")
    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in v):
        raise ValueError("Password must contain at least 1 special character")
    return v


class PinPasswordResetRequest(BaseModel):
    """Request to reset password using recovery PIN"""

    username: str = Field(..., min_length=3, max_length=255)
    recovery_pin: str = Field(..., min_length=4, max_length=4, pattern="^[0-9]{4}$")
    new_password: str = Field(..., min_length=8, max_length=BCRYPT_MAX_PASSWORD_BYTES)
    confirm_password: str = Field(..., min_length=8, max_length=BCRYPT_MAX_PASSWORD_BYTES)

    @field_validator("new_password")
    @classmethod
    def _check_password_strength(cls, v):
        return validate_password_strength(v)


class PinPasswordResetResponse(BaseModel):
    """Response after successful password reset via PIN"""

    message: str


class CheckFirstLoginRequest(BaseModel):
    """Request to check if first login is required"""

    username: str = Field(..., min_length=3, max_length=255)


class CheckFirstLoginResponse(BaseModel):
    """Response indicating if first login actions required"""

    must_change_password: bool
    must_set_pin: bool


class CompleteFirstLoginRequest(BaseModel):
    """Request to complete first login setup"""

    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=BCRYPT_MAX_PASSWORD_BYTES)
    confirm_password: str = Field(..., min_length=8, max_length=BCRYPT_MAX_PASSWORD_BYTES)
    recovery_pin: str | None = Field(default=None, min_length=4, max_length=4, pattern="^[0-9]{4}$")
    confirm_pin: str | None = Field(default=None, min_length=4, max_length=4, pattern="^[0-9]{4}$")

    @field_validator("new_password")
    @classmethod
    def _check_password_strength(cls, v):
        return validate_password_strength(v)


class CompleteFirstLoginResponse(BaseModel):
    """Response after completing first login"""

    message: str
