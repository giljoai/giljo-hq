# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest
from pydantic import ValidationError as PydanticValidationError

from giljo_mcp.schemas.user_approval import (
    ApprovalOption,
    RequestApprovalInput,
)


def test_request_approval_input_happy_path():
    payload = RequestApprovalInput(
        job_id="job-1",
        project_id="proj-1",
        reason="user decision required",
        options=[
            ApprovalOption(id="approve", label="Approve"),
            ApprovalOption(id="reject", label="Reject"),
        ],
        context={"k": "v"},
    )
    assert len(payload.options) == 2


def test_request_approval_input_rejects_empty_options():
    with pytest.raises(PydanticValidationError):
        RequestApprovalInput(
            job_id="job-1",
            project_id="proj-1",
            reason="x",
            options=[],
            context=None,
        )


def test_request_approval_input_rejects_duplicate_option_ids():
    with pytest.raises(PydanticValidationError):
        RequestApprovalInput(
            job_id="job-1",
            project_id="proj-1",
            reason="x",
            options=[
                {"id": "same", "label": "A"},
                {"id": "same", "label": "B"},
            ],
            context=None,
        )


def test_request_approval_input_rejects_too_many_options():
    with pytest.raises(PydanticValidationError):
        RequestApprovalInput(
            job_id="job-1",
            project_id="proj-1",
            reason="x",
            options=[{"id": f"opt-{i}", "label": f"L{i}"} for i in range(11)],
            context=None,
        )


def test_request_approval_input_rejects_oversized_reason():
    with pytest.raises(PydanticValidationError):
        RequestApprovalInput(
            job_id="job-1",
            project_id="proj-1",
            reason="x" * 2001,
            options=[{"id": "ok", "label": "OK"}],
            context=None,
        )


def test_request_approval_input_rejects_extra_fields():
    with pytest.raises(PydanticValidationError):
        RequestApprovalInput(
            job_id="job-1",
            project_id="proj-1",
            reason="x",
            options=[{"id": "ok", "label": "OK"}],
            context=None,
            unexpected="boom",
        )


def test_approval_option_rejects_blank_id():
    with pytest.raises(PydanticValidationError):
        ApprovalOption(id="", label="L")
