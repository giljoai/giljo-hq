# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from pathlib import Path

from giljo_mcp.domain.project_status import PROJECT_STATUS_META


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN_SCSS = _REPO_ROOT / "frontend" / "src" / "styles" / "main.scss"


def test_main_scss_file_exists() -> None:

    assert _MAIN_SCSS.is_file(), (
        f"main.scss not found at {_MAIN_SCSS}. The frontend StatusBadge "
        "resolves color_token strings against CSS custom properties declared "
        "here. If you moved the file, update this test."
    )


def test_every_status_color_token_is_declared_in_main_scss() -> None:

    text = _MAIN_SCSS.read_text(encoding="utf-8")

    tokens = {meta.color_token for meta in PROJECT_STATUS_META.values()}
    assert tokens, "PROJECT_STATUS_META has no color tokens; check the enum."

    missing: list[str] = []
    for token in sorted(tokens):
        pattern = re.compile(rf"^\s*--{re.escape(token)}\s*:", re.MULTILINE)
        if not pattern.search(text):
            missing.append(token)

    assert not missing, (
        f"PROJECT_STATUS_META declares color tokens that are NOT defined as CSS "
        f"custom properties in {_MAIN_SCSS}: {missing}. "
        "StatusBadge.vue will silently fall back to muted gray. "
        "Either add `--<token>: <hex>;` declarations to main.scss or update "
        "PROJECT_STATUS_META to use existing tokens."
    )


def test_no_hex_literal_in_project_status_meta() -> None:

    hex_pattern = re.compile(r"^#[0-9a-fA-F]{3,8}$")
    for member, meta in PROJECT_STATUS_META.items():
        assert not hex_pattern.match(meta.color_token), (
            f"PROJECT_STATUS_META[{member.name}].color_token is a hex literal "
            f"({meta.color_token!r}). Use a SCSS custom-property name like "
            "'color-status-complete' instead."
        )
