# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9208 D2 — picker-layer regression: is_default-first sort starves user templates.

Bug: ``select_templates_for_packaging`` (template_renderer.py) sorted ``is_default``
FIRST, then capped the result. A tenant with >= cap active default templates therefore
shipped ZERO user-created templates — directly contradicting the function's own
docstring ("users control which templates are enabled via UI toggle").

Fix: user-created templates outrank the seeded defaults (is_default is a low-priority
tiebreak only); the cap is 16 (raised from 8, BE-9208); the omitted set is
logged at WARNING so nothing is silently starved.

These tests assert the CORRECT post-fix behavior and were RED on the pre-fix picker.

Pure-unit (no DB, no I/O): parallel-safe by construction — every test builds its own
in-memory AgentTemplate objects with no shared mutable state and no ordering deps.

Project: BE-9208.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from giljo_mcp.models import AgentTemplate
from giljo_mcp.template_renderer import MAX_PACKAGED_TEMPLATES, select_templates_for_packaging


_BASE = datetime(2026, 7, 1, tzinfo=UTC)


def _tmpl(name: str, *, is_default: bool, minutes: int = 0) -> AgentTemplate:
    """Build an in-memory active AgentTemplate for picker tests."""
    return AgentTemplate(
        name=name,
        role=name,
        is_active=True,
        is_default=is_default,
        updated_at=_BASE + timedelta(minutes=minutes),
    )


def _names(selected: list[AgentTemplate]) -> set[str]:
    return {t.name for t in selected}


def test_cap_is_sixteen():
    """Contract lock: the packaging cap is 16 (raised from 8)."""
    assert MAX_PACKAGED_TEMPLATES == 16


def test_user_created_win_over_defaults_at_cap():
    """cap seeded defaults + 3 user templates -> all 3 user templates must ship.

    Pre-fix: the defaults sort first and consume the whole cap, so the user's own
    agents are entirely omitted from the export.
    """
    defaults = [_tmpl(f"default-{i}", is_default=True, minutes=i) for i in range(16)]
    customs = [_tmpl(f"user-{i}", is_default=False, minutes=100 + i) for i in range(3)]

    selected = select_templates_for_packaging(defaults + customs)

    assert len(selected) == 16
    picked = _names(selected)
    for c in customs:
        assert c.name in picked, f"user template {c.name!r} was starved by seeded defaults"


def test_exactly_cap_all_selected():
    """A tenant with exactly `cap` active templates ships all of them (cap lock)."""
    mix = [_tmpl(f"default-{i}", is_default=True, minutes=i) for i in range(8)]
    mix += [_tmpl(f"user-{i}", is_default=False, minutes=50 + i) for i in range(8)]

    selected = select_templates_for_packaging(mix)

    assert len(selected) == 16
    assert _names(selected) == {t.name for t in mix}


def test_over_cap_prefers_user_created():
    """13 defaults + 6 user templates (19 active, cap 16) -> all 6 user templates ship.

    When actives exceed the cap, user-created templates are preferred; defaults
    fill only the remaining slots.
    """
    defaults = [_tmpl(f"default-{i}", is_default=True, minutes=i) for i in range(13)]
    customs = [_tmpl(f"user-{i}", is_default=False, minutes=100 + i) for i in range(6)]

    selected = select_templates_for_packaging(defaults + customs)

    assert len(selected) == 16
    picked = _names(selected)
    for c in customs:
        assert c.name in picked, f"user template {c.name!r} lost its slot to a seeded default"
    # The 10 leftover slots go to defaults.
    assert sum(1 for t in selected if t.is_default) == 10


def test_omitted_templates_are_logged_not_silent(caplog):
    """Over-cap omission must be surfaced (WARNING listing omitted names), never silent."""
    defaults = [_tmpl(f"default-{i}", is_default=True, minutes=i) for i in range(20)]

    with caplog.at_level(logging.WARNING, logger="giljo_mcp.template_renderer"):
        selected = select_templates_for_packaging(defaults)

    assert len(selected) == 16
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected a WARNING when the active set exceeds the cap"
    msg = warnings[-1].getMessage()
    # The 4 omitted (lowest-precedence, oldest) default names must appear.
    omitted_names = _names(select_templates_for_packaging(defaults)) ^ {t.name for t in defaults}
    for name in omitted_names:
        assert name in msg, f"omitted template {name!r} not surfaced in the WARNING log"
