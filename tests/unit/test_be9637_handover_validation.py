# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.handover_validation import (
    HANDOVER_SHAPE_CONSTRAINT,
    HANDOVER_SHAPE_FIELD,
    HANDOVER_TYPE_ABBR,
    REQUIRED_HANDOVER_HEADINGS,
    handover_shape_message,
    missing_handover_headings,
    require_handover_shape,
)


COMPLETE = "\n\n".join(f"{heading}\n- something" for heading in REQUIRED_HANDOVER_HEADINGS)


def test_a_complete_handover_has_nothing_missing() -> None:
    assert missing_handover_headings(COMPLETE) == []


@pytest.mark.parametrize("omitted", REQUIRED_HANDOVER_HEADINGS)
def test_each_heading_is_independently_required(omitted: str) -> None:
    text = "\n\n".join(f"{h}\n- something" for h in REQUIRED_HANDOVER_HEADINGS if h != omitted)
    assert missing_handover_headings(text) == [omitted]


def test_missing_headings_come_back_in_document_order() -> None:
    assert missing_handover_headings("") == list(REQUIRED_HANDOVER_HEADINGS)


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_an_empty_description_is_missing_everything(empty) -> None:
    assert missing_handover_headings(empty) == list(REQUIRED_HANDOVER_HEADINGS)


def test_the_message_names_every_missing_heading_not_just_the_first() -> None:
    message = handover_shape_message(list(REQUIRED_HANDOVER_HEADINGS))
    for heading in REQUIRED_HANDOVER_HEADINGS:
        assert heading in message
    assert HANDOVER_TYPE_ABBR in message


def test_require_handover_shape_accepts_a_complete_one() -> None:
    require_handover_shape(COMPLETE, operation="create_task")


def test_require_handover_shape_raises_with_the_boundary_coordinates() -> None:
    with pytest.raises(ValidationError) as excinfo:
        require_handover_shape("nothing useful here", operation="create_task")
    exc = excinfo.value
    assert exc.context["field"] == HANDOVER_SHAPE_FIELD
    assert exc.context["constraint"] == HANDOVER_SHAPE_CONSTRAINT
    assert exc.context["operation"] == "create_task"
    assert exc.context["missing_headings"] == list(REQUIRED_HANDOVER_HEADINGS)


def test_the_headings_are_matched_as_written_not_loosely() -> None:
    assert missing_handover_headings("## cannot testify") != []
    assert missing_handover_headings("Cannot testify") != []
    assert "## Cannot testify" not in missing_handover_headings(COMPLETE)


def test_extra_content_around_the_headings_is_fine() -> None:
    rich = f"Narrative opening.\n\n## Team state\n- someone\n\n{COMPLETE}\n\n## Notes\n- more"
    assert missing_handover_headings(rich) == []
