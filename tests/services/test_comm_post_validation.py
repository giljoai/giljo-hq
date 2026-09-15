# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.comm import VALID_SELF_REPORTED_STATUSES
from giljo_mcp.services.comm_post_validation import (
    SETTABLE_THREAD_STATUSES,
    validate_post_vocabularies,
)


def test_omitting_both_fields_is_always_acceptable():
    assert validate_post_vocabularies(None, None) is None


@pytest.mark.parametrize("status", VALID_SELF_REPORTED_STATUSES)
def test_every_locked_self_reported_status_is_accepted(status):
    assert validate_post_vocabularies(None, status) is None


@pytest.mark.parametrize("status", SETTABLE_THREAD_STATUSES)
def test_every_settable_thread_status_is_accepted(status):
    assert validate_post_vocabularies(status, None) is None


def test_unknown_self_reported_status_is_refused_and_names_the_valid_set():
    with pytest.raises(ValidationError) as exc:
        validate_post_vocabularies(None, "grinding")
    message = str(exc.value)
    assert "grinding" in message
    for valid in VALID_SELF_REPORTED_STATUSES:
        assert valid in message


def test_unknown_thread_status_is_refused():
    with pytest.raises(ValidationError) as exc:
        validate_post_vocabularies("archived", None)
    assert "archived" in str(exc.value)


def test_execution_only_statuses_are_not_self_awardable():
    for platform_only in ("closed", "silent", "decommissioned", "awaiting_user", "staged"):
        assert platform_only not in VALID_SELF_REPORTED_STATUSES
        with pytest.raises(ValidationError):
            validate_post_vocabularies(None, platform_only)


def test_the_two_vocabularies_are_checked_independently():
    with pytest.raises(ValidationError):
        validate_post_vocabularies("open", "grinding")
    with pytest.raises(ValidationError):
        validate_post_vocabularies("archived", "working")
