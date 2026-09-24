# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.handover_validation import (
    HANDOVER_CONTENT_CONSTRAINT,
    HANDOVER_SHAPE_CONSTRAINT,
    HANDOVER_SHAPE_FIELD,
    REQUIRED_HANDOVER_HEADINGS,
    empty_handover_headings,
    require_handover_shape,
)


FILLED = """Session ended at the rebase.

## Verify before trusting
- the branch is green -- check with: pytest tests/unit -q

## Waiting on the operator
- nothing

## Cannot testify
- the concurrency behaviour; never observed it
"""

SKELETON = "\n\n".join(REQUIRED_HANDOVER_HEADINGS) + "\n"


def test_a_filled_handover_has_no_empty_sections() -> None:
    assert empty_handover_headings(FILLED) == []


def test_the_pre_filled_skeleton_is_entirely_empty() -> None:
    assert empty_handover_headings(SKELETON) == list(REQUIRED_HANDOVER_HEADINGS)


def test_nothing_counts_as_content() -> None:
    text = "## Verify before trusting\nnothing\n\n## Waiting on the operator\nnothing\n\n## Cannot testify\nnothing\n"
    assert empty_handover_headings(text) == []


def test_a_heading_followed_only_by_the_next_heading_is_empty() -> None:
    text = "## Verify before trusting\n- a claim -- check with: x\n\n## Waiting on the operator\n\n## Cannot testify\n- nothing\n"
    assert empty_handover_headings(text) == ["## Waiting on the operator"]


def test_a_heading_followed_only_by_blank_lines_is_empty() -> None:
    text = (
        "## Verify before trusting\n   \n\t\n\n## Waiting on the operator\n- nothing\n\n## Cannot testify\n- nothing\n"
    )
    assert empty_handover_headings(text) == ["## Verify before trusting"]


def test_content_on_the_heading_line_itself_counts() -> None:
    text = "## Verify before trusting: ran the suite\n\n## Waiting on the operator: nothing\n\n## Cannot testify: nothing\n"
    assert empty_handover_headings(text) == []


def test_a_missing_heading_is_not_reported_as_empty() -> None:
    text = "## Verify before trusting\n- x -- check with: y\n\n## Cannot testify\n- nothing\n"
    assert empty_handover_headings(text) == []


def test_require_handover_shape_refuses_an_empty_section() -> None:
    with pytest.raises(ValidationError) as excinfo:
        require_handover_shape(SKELETON, operation="create_task")

    assert excinfo.value.context["field"] == HANDOVER_SHAPE_FIELD
    assert excinfo.value.context["constraint"] == HANDOVER_CONTENT_CONSTRAINT
    assert excinfo.value.context["empty_headings"] == list(REQUIRED_HANDOVER_HEADINGS)
    for heading in REQUIRED_HANDOVER_HEADINGS:
        assert heading in excinfo.value.message


def test_a_missing_heading_still_wins_over_an_empty_one() -> None:
    text = "## Verify before trusting\n\n## Waiting on the operator\n- nothing\n"
    with pytest.raises(ValidationError) as excinfo:
        require_handover_shape(text, operation="create_task")

    assert excinfo.value.context["constraint"] == HANDOVER_SHAPE_CONSTRAINT


def test_a_complete_handover_still_passes() -> None:
    require_handover_shape(FILLED, operation="create_task")
