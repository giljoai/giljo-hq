# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import re


MAX_NAME_SUFFIX = 20


def crew_suffixed_names(base_names: list[str], taken_names: set[str]) -> tuple[list[str], int] | None:
    for n in range(1, MAX_NAME_SUFFIX + 1):
        candidates = [base if n == 1 else f"{base}-{n}" for base in base_names]
        if not any(c in taken_names for c in candidates):
            return candidates, n
    return None


def slugify_name(role: str, suffix: str | None = None) -> str:
    if suffix:
        suffix_clean = re.sub(r"[^a-z0-9-]", "", suffix.lower().replace("_", "-").replace(" ", "-")).strip("-")
        suffix_clean = re.sub(r"-{2,}", "-", suffix_clean)
        if suffix_clean:
            return f"{role}-{suffix_clean}"
    return role


def get_role_color(role: str) -> str:
    color_map = {
        "orchestrator": "#D4A574",
        "analyzer": "#E74C3C",
        "designer": "#9B59B6",
        "frontend": "#3498DB",
        "backend": "#2ECC71",
        "implementer": "#3498DB",
        "tester": "#FFC300",
        "reviewer": "#9B59B6",
        "documenter": "#27AE60",
    }
    return color_map.get(role, "#90A4AE")
