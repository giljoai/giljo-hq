# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from typing import Any


MAX_PACKAGED_TEMPLATES = 16


def _slugify_filename(name: str) -> str:
    slug = name.strip().lower().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9._-]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "agent"


def hex_to_claude_color(hex_code: str | None) -> str | None:
    if not hex_code:
        return None

    normalized = hex_code.strip().upper()
    if not normalized.startswith("#"):
        normalized = f"#{normalized}"

    color_map = {
        "#D4A574": "orange",
        "#3498DB": "blue",
        "#FFC300": "yellow",
        "#E74C3C": "red",
        "#9B59B6": "purple",
        "#27AE60": "green",
        "#2ECC71": "green",
        "#90A4AE": "grey",
    }

    return color_map.get(normalized)


def profile_markdown_filename(name: str) -> str:
    return f"{_slugify_filename(name or 'agent')}-profile.md"


def render_profile_markdown(profile: dict[str, Any]) -> str:
    lines: list[str] = [
        f"# {profile.get('name') or 'Agent'}",
        "",
        "## Description",
        (profile.get("description") or "").strip(),
        "",
        "## Model / Effort",
        f"{profile.get('model') or 'inherit'} / {profile.get('effort') or 'inherit'}",
        "",
        "## Profile instructions",
        (profile.get("instructions") or "").strip(),
    ]
    rules = [str(r) for r in (profile.get("behavioral_rules") or []) if str(r).strip()]
    if rules:
        lines += ["", "Behavioral rules:", *[f"- {r}" for r in rules]]
    criteria = [str(c) for c in (profile.get("success_criteria") or []) if str(c).strip()]
    if criteria:
        lines += ["", "Success criteria:", *[f"- {c}" for c in criteria]]
    return "\n".join(lines).rstrip() + "\n"
