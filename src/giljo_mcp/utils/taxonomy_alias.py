# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations


def format_taxonomy_alias(
    abbreviation: str | None,
    series_number: int | None,
    subseries: str | None = None,
    *,
    fallback: str = "",
) -> str:
    abbr = abbreviation or ""
    if series_number is None:
        return abbr or fallback
    padded = str(series_number).zfill(4)
    sep = "-" if abbr else ""
    return f"{abbr}{sep}{padded}{subseries or ''}"
