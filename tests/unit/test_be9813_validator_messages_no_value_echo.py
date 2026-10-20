# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from giljo_mcp.schemas import jsonb_validators as jv
from giljo_mcp.schemas.jsonb_validators_sequence_runs import (
    validate_sequence_run_project_ids,
    validate_sequence_run_project_statuses,
    validate_sequence_run_reviewed_project_ids,
    validate_sequence_run_reviewed_via,
)
from giljo_mcp.schemas.user_approval import UserApprovalRead


MARKER = "be9813marker"


def _messages(exc: BaseException) -> str:
    if isinstance(exc, ValidationError):
        return " | ".join(err["msg"] for err in exc.errors())
    return str(exc)


def _approval_row(banner_state: str) -> dict:
    return {
        "id": "a1",
        "tenant_key": "tk",
        "agent_execution_id": "e1",
        "job_id": "j1",
        "project_id": "p1",
        "reason": "r",
        "options": [],
        "context": None,
        "status": "pending",
        "decided_option_id": None,
        "decided_by_user_id": None,
        "decided_via": None,
        "requested_at": datetime.now(UTC),
        "decided_at": None,
        "banner_state": banner_state,
    }


CASES = [
    ("banner_state", lambda: UserApprovalRead(**_approval_row(MARKER))),
    ("Tool name", lambda: jv.validate_setup_selected_tools([MARKER + "t" * 300])),
    ("redirect_uri", lambda: jv.validate_oauth_client_redirect_uris(["https://" + MARKER + "x" * 2100])),
    ("Keyword", lambda: jv.validate_context_keywords([MARKER + "k" * 600])),
    ("doc_id", lambda: jv.validate_vision_summaries([{"doc_id": MARKER, "light": "l", "medium": "m"}])),
    ("storage_object_key_sha256s", lambda: jv.DeletionReceiptStorageKeyHashes(items=[MARKER])),
    ("project_id", lambda: validate_sequence_run_project_ids([MARKER + "p" * 40])),
    ("reviewed project_id", lambda: validate_sequence_run_reviewed_project_ids([MARKER + "p" * 40])),
    ("project_id key", lambda: validate_sequence_run_project_statuses({MARKER + "p" * 40: "active"})),
    ("project_statuses", lambda: validate_sequence_run_project_statuses({"p1": MARKER})),
    ("reviewed_via", lambda: validate_sequence_run_reviewed_via({"p1": MARKER})),
]


@pytest.mark.parametrize(("field_words", "trigger"), CASES, ids=[c[0] for c in CASES])
def test_rejection_names_the_field_but_not_the_value(field_words, trigger):
    with pytest.raises((ValueError, TypeError)) as excinfo:
        trigger()
    text = _messages(excinfo.value)
    assert MARKER not in text, f"rejected value echoed: {text}"
    assert field_words in text, f"message no longer names the field: {text}"
