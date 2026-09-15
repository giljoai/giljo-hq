# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


STOPWORDS: frozenset[str] = frozenset(
    {
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
    }
)

STRIP_CHARS = "(),:;.!?"

MAX_TAG_LENGTH = 50
MAX_TAGS = 15


def strip_tag_punctuation(tag: str) -> str:
    return tag.strip().strip(STRIP_CHARS)


def sanitize_tag(tag: str) -> str:
    return strip_tag_punctuation(tag)[:MAX_TAG_LENGTH]


def clean_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []

    result: list[str] = []
    seen_lower: set[str] = set()

    for tag in tags:
        cleaned = sanitize_tag(tag)

        if not cleaned:
            continue

        if cleaned.lower() in STOPWORDS:
            continue

        lower_key = cleaned.lower()
        if lower_key in seen_lower:
            continue
        seen_lower.add(lower_key)

        result.append(cleaned)

        if len(result) >= MAX_TAGS:
            break

    return result
