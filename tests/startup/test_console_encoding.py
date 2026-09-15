# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import MagicMock, patch

import pytest

from startup_support.console import _safe


@pytest.mark.parametrize(
    ("encoding", "text", "expected"),
    [
        ("cp1252", "SSL cert/key files not found — falling back to HTTP", None),
        ("cp1252", "✓ all checks passed", "OK all checks passed"),
        (
            "cp437",
            "npm not found in PATH — skipping frontend rebuild",
            "npm not found in PATH - skipping frontend rebuild",
        ),
        ("utf-8", "→ branch order — saas first ✓", None),
    ],
)
def test_safe_falls_back_on_unencodable_glyphs(encoding, text, expected):
    with patch("startup_support.console.sys.stdout", MagicMock(encoding=encoding)):
        result = _safe(text)

    if expected is None:
        assert result == text
    else:
        assert result == expected
    result.encode(encoding)


def test_safe_defaults_to_utf8_when_stdout_encoding_is_unset():
    with patch("startup_support.console.sys.stdout", MagicMock(encoding=None)):
        assert _safe("— fine on utf-8 —") == "— fine on utf-8 —"
