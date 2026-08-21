# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9475 — the closed vocabularies a Hub post may carry.

Covers the path the MCP-boundary suite deliberately cannot reach. That suite
(``tests/integration/test_be9475_participant_self_reported_status_mcp_boundary.py``)
drives the ``@mcp.tool`` wrapper, which refuses a bad ``my_status`` with a structured
domain rejection before the service is ever called. The REST endpoint and every internal
caller reach ``CommThreadService.post_to_thread`` WITHOUT that wrapper, so the owning
service does its own check — and that backstop needs its own evidence, because a test
that only ever enters through the boundary would stay green even if the service-level
check were deleted outright.

Pure functions, no DB, no fixtures, no module-level mutable state.
"""

from __future__ import annotations

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.comm import VALID_SELF_REPORTED_STATUSES
from giljo_mcp.services.comm_post_validation import (
    SETTABLE_THREAD_STATUSES,
    validate_post_vocabularies,
)


def test_omitting_both_fields_is_always_acceptable():
    """None means "not supplied", for both fields.

    The overwhelmingly common post carries neither, and a check that turned an ordinary
    broadcast into an error would be a far worse defect than the one BE-9475 fixed.
    """
    assert validate_post_vocabularies(None, None) is None


@pytest.mark.parametrize("status", VALID_SELF_REPORTED_STATUSES)
def test_every_locked_self_reported_status_is_accepted(status):
    """Each of the six is accepted — the tuple and this validator cannot drift apart."""
    assert validate_post_vocabularies(None, status) is None


@pytest.mark.parametrize("status", SETTABLE_THREAD_STATUSES)
def test_every_settable_thread_status_is_accepted(status):
    assert validate_post_vocabularies(status, None) is None


def test_unknown_self_reported_status_is_refused_and_names_the_valid_set():
    """The message must carry the vocabulary: the caller is usually an agent, and a
    refusal it cannot act on just becomes a retry loop."""
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
    """The self-reported vocabulary is deliberately NARROWER than
    ``agent_executions.status``.

    ``closed``, ``silent``, ``decommissioned``, ``awaiting_user`` and ``staged`` are
    lifecycle facts the PLATFORM establishes about an agent it is running. An agent
    awarding itself ``decommissioned`` — or ``awaiting_user``, which drives the gold
    approval card — would let a self-declaration drive operator-facing state it has no
    authority over. Pinned here so widening the tuple has to be a deliberate act.
    """
    for platform_only in ("closed", "silent", "decommissioned", "awaiting_user", "staged"):
        assert platform_only not in VALID_SELF_REPORTED_STATUSES
        with pytest.raises(ValidationError):
            validate_post_vocabularies(None, platform_only)


def test_the_two_vocabularies_are_checked_independently():
    """A valid value in one field never excuses an invalid value in the other."""
    with pytest.raises(ValidationError):
        validate_post_vocabularies("open", "grinding")
    with pytest.raises(ValidationError):
        validate_post_vocabularies("archived", "working")
