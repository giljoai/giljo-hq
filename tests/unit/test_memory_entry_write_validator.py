# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.services.memory_entry_write_validator import (
    MEMORY_SUMMARY_MAX,
    MemoryEntryWriteSchema,
    MemoryEntryWriteValidationError,
    validate_memory_entry_write,
)


def test_public_surface_importable():
    assert MEMORY_SUMMARY_MAX == 1500
    assert issubclass(MemoryEntryWriteSchema, object)
    assert issubclass(MemoryEntryWriteValidationError, Exception)


def test_validator_accepts_minimal_valid_payload():
    schema = validate_memory_entry_write(
        {
            "summary": "Headline summary.",
            "key_outcomes": ["A"],
            "decisions_made": ["D"],
            "deliverables": [],
            "tags": ["bug-fix"],
        }
    )
    assert schema.summary == "Headline summary."


def test_validator_rejects_oversize_summary_with_structured_error():
    with pytest.raises(MemoryEntryWriteValidationError) as exc_info:
        validate_memory_entry_write(
            {
                "summary": "x" * 1600,
                "key_outcomes": [],
                "decisions_made": [],
                "deliverables": [],
                "tags": [],
            }
        )
    err = exc_info.value
    assert err.error == "validation_failed"
    assert err.field == "summary"
    assert err.actual_size == 1600
    assert err.max_size == 1500


def test_batch_reports_all_failing_caps_together():
    with pytest.raises(MemoryEntryWriteValidationError) as exc_info:
        validate_memory_entry_write(
            {
                "summary": "x" * 1600,
                "key_outcomes": ["a", "b", "c", "d", "e", "f"],
                "decisions_made": [],
                "deliverables": [],
                "tags": ["not-a-real-tag"],
            }
        )
    err = exc_info.value
    assert err.all_failures is not None
    offending = {f["field"] for f in err.all_failures}
    assert {"summary", "key_outcomes", "tags"} <= offending
    assert "all_failures" in err.to_dict()


def test_single_failure_has_no_all_failures():
    with pytest.raises(MemoryEntryWriteValidationError) as exc_info:
        validate_memory_entry_write(
            {
                "summary": "x" * 1600,
                "key_outcomes": [],
                "decisions_made": [],
                "deliverables": [],
                "tags": [],
            }
        )
    err = exc_info.value
    assert err.all_failures is None
    assert "all_failures" not in err.to_dict()


def test_validator_rejects_unknown_tag():
    with pytest.raises(MemoryEntryWriteValidationError) as exc_info:
        validate_memory_entry_write(
            {
                "summary": "ok",
                "key_outcomes": [],
                "decisions_made": [],
                "deliverables": [],
                "tags": ["NOT a slug!"],
            }
        )
    assert exc_info.value.field == "tags"


def test_str_skips_only_the_primarys_own_entry_not_every_same_field_entry():
    err = MemoryEntryWriteValidationError(
        field="decisions_made",
        actual_size=300,
        max_size=250,
        guidance="Trim it.",
        all_failures=[
            {
                "error": "validation_failed",
                "field": "decisions_made",
                "actual_size": 300,
                "max_size": 250,
                "guidance": "Trim it.",
            },
            {
                "error": "validation_failed",
                "field": "decisions_made",
                "actual_size": 400,
                "max_size": 250,
                "guidance": "Trim the second one too.",
            },
        ],
    )
    text = str(err)
    assert text.count("decisions_made") == 2, f"second same-field violation dropped: {text!r}"
    assert "Trim the second one too." in text, f"second violation's guidance missing from wire text: {text!r}"
