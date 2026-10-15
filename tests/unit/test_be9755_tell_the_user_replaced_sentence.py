# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime

import pytest

from giljo_mcp.services.template_proposal_service import replaced_sentence


SAVED = datetime(2026, 10, 9, 5, 16, tzinfo=UTC)


@pytest.mark.parametrize(
    ("reason", "ending"),
    [
        ("Make line two concrete.", "Make line two concrete."),
        ("Make line two concrete", "Make line two concrete."),
        ("Is line two stale?", "Is line two stale?"),
        ("  Trailing space.  ", "Trailing space."),
    ],
)
def test_replaced_sentence_ends_with_one_terminal_mark(reason, ending):
    sentence = replaced_sentence(SAVED, reason)
    assert sentence.endswith(ending)
    assert "2026-10-09" in sentence
    assert ".)." not in sentence and ".." not in sentence and "?." not in sentence
