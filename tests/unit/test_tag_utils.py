# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from giljo_mcp.utils.tag_utils import clean_tags, sanitize_tag, strip_tag_punctuation


class TestStripTagPunctuation:

    def test_strips_boundary_punctuation(self):
        assert strip_tag_punctuation("(refactor)") == "refactor"

    def test_preserves_long_tags(self):
        long_tag = "a" * 200
        assert strip_tag_punctuation(long_tag) == long_tag

    def test_strips_whitespace(self):
        assert strip_tag_punctuation("  hello  ") == "hello"

    def test_empty_string_returns_empty(self):
        assert strip_tag_punctuation("") == ""

    def test_all_punctuation_returns_empty(self):
        assert strip_tag_punctuation("(),:;.!?") == ""

    def test_strips_all_strip_chars_from_boundaries(self):
        assert strip_tag_punctuation("(),:;.!?hello(),:;.!?") == "hello"


class TestSanitizeTag:

    def test_strips_trailing_punctuation(self):
        assert sanitize_tag("refactor.") == "refactor"

    def test_strips_leading_punctuation(self):
        assert sanitize_tag("(refactor") == "refactor"

    def test_strips_both_sides(self):
        assert sanitize_tag("(refactor)") == "refactor"

    def test_strips_multiple_punctuation_chars(self):
        assert sanitize_tag("...hello!!!") == "hello"

    def test_truncates_to_50_chars(self):
        long_tag = "a" * 80
        result = sanitize_tag(long_tag)
        assert len(result) == 50

    def test_preserves_valid_tag(self):
        assert sanitize_tag("fastapi") == "fastapi"

    def test_preserves_internal_punctuation(self):
        assert sanitize_tag("bug_fix:auth_timeout") == "bug_fix:auth_timeout"

    def test_strips_colons_from_ends(self):
        assert sanitize_tag(":tagged:") == "tagged"

    def test_empty_after_strip_returns_empty(self):
        assert sanitize_tag("...") == ""

    def test_whitespace_stripped(self):
        assert sanitize_tag("  hello  ") == "hello"


class TestCleanTags:

    def test_filters_stopwords(self):
        tags = ["the", "refactor", "from", "database"]
        result = clean_tags(tags)
        assert "the" not in result
        assert "from" not in result
        assert "refactor" in result
        assert "database" in result

    def test_stopword_filtering_case_insensitive(self):
        tags = ["The", "FROM", "refactor"]
        result = clean_tags(tags)
        assert "The" not in result
        assert "FROM" not in result
        assert "refactor" in result

    def test_strips_punctuation_from_tags(self):
        tags = ["(refactor)", "database.", "!important!"]
        result = clean_tags(tags)
        assert "refactor" in result
        assert "database" in result
        assert "important" in result

    def test_dedup_case_insensitive_keeps_first(self):
        tags = ["Refactor", "refactor", "REFACTOR"]
        result = clean_tags(tags)
        assert result == ["Refactor"]

    def test_max_15_tags(self):
        tags = [f"tag{i}" for i in range(30)]
        result = clean_tags(tags)
        assert len(result) <= 15

    def test_max_50_chars_per_tag(self):
        tags = ["a" * 80, "short"]
        result = clean_tags(tags)
        for tag in result:
            assert len(tag) <= 50

    def test_empty_tags_after_strip_removed(self):
        tags = ["...", "valid", "()"]
        result = clean_tags(tags)
        assert result == ["valid"]

    def test_none_input_returns_empty(self):
        result = clean_tags(None)
        assert result == []

    def test_empty_list_returns_empty(self):
        result = clean_tags([])
        assert result == []

    def test_preserves_tags_with_internal_colon(self):
        tags = ["bug_fix:auth_timeout", "refactor"]
        result = clean_tags(tags)
        assert "bug_fix:auth_timeout" in result

    def test_combined_pipeline(self):
        tags = ["The", "(database)", "database", "from", "refactor.", "auth"]
        result = clean_tags(tags)
        assert "The" not in result
        assert "from" not in result
        assert "database" in result
        assert len([t for t in result if t.lower() == "database"]) == 1
        assert "refactor" in result
        assert "auth" in result

    def test_filters_all_28_stopwords(self):
        all_stopwords = [
            "from",
            "with",
            "the",
            "and",
            "for",
            "in",
            "to",
            "of",
            "a",
            "an",
            "is",
            "on",
            "at",
            "by",
            "or",
            "as",
            "it",
            "that",
            "this",
            "was",
            "are",
            "be",
            "has",
            "had",
            "not",
            "but",
            "all",
            "can",
        ]
        assert len(all_stopwords) == 28
        result = clean_tags(all_stopwords)
        assert result == [], f"Expected empty result, got {result}"

    def test_single_char_tag_not_stopword_preserved(self):
        result = clean_tags(["a", "x"])
        assert "a" not in result
        assert "x" in result

    def test_non_list_type_returns_empty(self):
        assert clean_tags("") == []
        assert clean_tags(0) == []
