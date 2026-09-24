# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.handover_template import (
    DEFAULT_HANDOVER_TEMPLATE,
    HANDOVER_TEMPLATE_FIELD,
    HANDOVER_TEMPLATE_LENGTH_CONSTRAINT,
    HANDOVER_TEMPLATE_MAX_CHARS,
    normalize_handover_template,
    require_template_within_cap,
    resolve_handover_template,
)
from giljo_mcp.services.handover_validation import REQUIRED_HANDOVER_HEADINGS, missing_handover_headings


def test_the_default_template_carries_every_required_heading() -> None:
    assert missing_handover_headings(DEFAULT_HANDOVER_TEMPLATE) == []


def test_the_default_template_carries_the_references_section() -> None:
    assert "## References" in DEFAULT_HANDOVER_TEMPLATE


def test_the_default_template_fits_the_cap_it_ships_with() -> None:
    require_template_within_cap(DEFAULT_HANDOVER_TEMPLATE, operation="default")


@pytest.mark.parametrize("omitted", REQUIRED_HANDOVER_HEADINGS)
def test_a_missing_required_heading_is_appended_not_refused(omitted: str) -> None:
    custom = "## Context\nwhat this session was.\n\n" + "\n\n".join(
        f"{heading}\n- ..." for heading in REQUIRED_HANDOVER_HEADINGS if heading != omitted
    )

    normalized = normalize_handover_template(custom)

    assert missing_handover_headings(normalized) == []
    assert omitted in normalized
    assert "## Context" in normalized, "the operator's own sections survive"


def test_a_template_that_already_has_them_is_left_alone() -> None:
    assert normalize_handover_template(DEFAULT_HANDOVER_TEMPLATE) == DEFAULT_HANDOVER_TEMPLATE


def test_an_empty_template_normalizes_to_the_three_headings() -> None:
    normalized = normalize_handover_template("")
    assert missing_handover_headings(normalized) == []


def test_extra_sections_are_the_point() -> None:
    custom = DEFAULT_HANDOVER_TEMPLATE + "\n## Runbooks\n- one per line\n"
    assert "## Runbooks" in normalize_handover_template(custom)


def test_an_over_length_template_is_refused_with_the_structured_shape() -> None:
    with pytest.raises(ValidationError) as excinfo:
        require_template_within_cap("x" * (HANDOVER_TEMPLATE_MAX_CHARS + 1), operation="update_handover_template")

    assert excinfo.value.context["field"] == HANDOVER_TEMPLATE_FIELD
    assert excinfo.value.context["constraint"] == HANDOVER_TEMPLATE_LENGTH_CONSTRAINT
    assert str(HANDOVER_TEMPLATE_MAX_CHARS) in excinfo.value.message


def test_a_template_exactly_at_the_cap_is_accepted() -> None:
    require_template_within_cap("x" * HANDOVER_TEMPLATE_MAX_CHARS, operation="update_handover_template")


def test_an_account_that_never_set_one_resolves_to_the_default() -> None:
    assert resolve_handover_template(None) == DEFAULT_HANDOVER_TEMPLATE
    assert resolve_handover_template("") == DEFAULT_HANDOVER_TEMPLATE
    assert resolve_handover_template("   \n ") == DEFAULT_HANDOVER_TEMPLATE


def test_a_stored_template_resolves_normalized() -> None:
    stored = "## Context\njust this.\n"
    resolved = resolve_handover_template(stored)
    assert missing_handover_headings(resolved) == []
    assert "## Context" in resolved
