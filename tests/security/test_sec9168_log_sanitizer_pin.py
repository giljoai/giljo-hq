# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import uuid

from giljo_mcp.utils.log_sanitizer import mask_token, sanitize


class TestSanitizePinnedBehavior:

    def test_plain_string_unchanged(self):
        assert sanitize("agent-alpha finished step 3") == "agent-alpha finished step 3"

    def test_empty_string(self):
        assert sanitize("") == ""

    def test_newline_variants_removed(self):
        assert sanitize("a\r\nb") == "ab"
        assert sanitize("a\rb\nc") == "abc"
        assert sanitize("line1\nline2\nline3") == "line1line2line3"

    def test_control_chars_removed(self):
        assert sanitize("a\tb") == "ab"
        assert sanitize("a\x00b\x1bc\x7fd") == "abcd"

    def test_forged_log_line_neutralized(self):
        forged = "user1\n2026-07-14 INFO fake entry"
        assert sanitize(forged) == "user12026-07-14 INFO fake entry"

    def test_unicode_preserved(self):
        assert sanitize("naïve café — ünïcode ✓") == "naïve café — ünïcode ✓"

    def test_non_str_int(self):
        assert sanitize(42) == "42"

    def test_non_str_none(self):
        assert sanitize(None) == "None"

    def test_non_str_uuid(self):
        u = uuid.UUID("e8e2a966-dd8d-45dc-b4a8-9b08d63bc5b5")
        assert sanitize(u) == "e8e2a966-dd8d-45dc-b4a8-9b08d63bc5b5"

    def test_non_str_exception_clean_message(self):
        assert sanitize(ValueError("bad input")) == "bad input"

    def test_return_type_is_str(self):
        assert isinstance(sanitize(42), str)
        assert isinstance(sanitize("x"), str)


class TestMaskTokenPinnedBehavior:

    def test_long_token_masked(self):
        assert mask_token("a1b2c3d4e5f6") == "a1b2c3d4..."

    def test_short_token_passthrough(self):
        assert mask_token("short") == "short"

    def test_exactly_eight_chars_passthrough(self):
        assert mask_token("12345678") == "12345678"

    def test_non_str_token(self):
        assert mask_token(12345) == "12345"


class TestMaskTokenStripsControlChars:

    def test_short_token_newline_stripped(self):
        assert mask_token("ab\ncd") == "abcd"

    def test_forged_line_token_neutralized(self):
        assert mask_token("x\n2026-07-14 INFO fake") == "x2026-0..."

    def test_long_token_control_chars_in_prefix_stripped(self):
        assert mask_token("a\rb\nc\td4e5f6g7h8") == "abcd4..."

    def test_masking_applies_before_stripping(self):
        assert mask_token("\x00abcdefgh") == "abcdefg..."
