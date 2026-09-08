# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""The account's standing answer to the one question staging asks (FE-9555).

Ruling 6 of the FE-9555 design session: "Execution mode must be ASKED, both
doors." Staging therefore refuses to choose ``multi_terminal`` vs ``subagent``
on a caller's behalf -- but a refusal with no off switch is a nag, so the ruling
pairs it with ONE account default, set in the dashboard under Tools -> Agents:
*ask every time* (the default) / *terminals* / *subagents*.

This module is deliberately separate from :mod:`giljo_mcp.platform_registry`,
which owns what the modes ARE. What a given ACCOUNT prefers is a different
concern with different consumers -- the settings REST endpoint writes it, the
staging tool reads it -- and neither should have to import the other. (The
registry is also sitting on its 800-line guardrail, which is the same message
from a different direction.)
"""

from __future__ import annotations

from giljo_mcp.platform_registry import EXECUTION_MODES, VALID_EXECUTION_MODES


# The stored value meaning "put the question to the user every time". The default
# when the account has never expressed a preference.
STAGE_MODE_ASK = "ask"

# Where the preference lives: SettingsService category ``general``, this key.
EXECUTION_MODE_DEFAULT_KEY = "execution_mode_default"

# The three choices the Tools -> Agents control offers, in display order. The two
# real modes come from the registry so the control cannot drift away from it.
EXECUTION_MODE_DEFAULT_CHOICES: tuple[str, ...] = (STAGE_MODE_ASK, *EXECUTION_MODES)


def default_stage_mode(setting_value: str | None) -> str:
    """Map the stored account default to a ``stage_project`` mode token.

    Returns ``""`` -- meaning ASK -- for ``ask``, for an unset value, and for any
    value that is not exactly one of the two canonical modes. Failing safe is the
    whole point: the behaviour FE-9555 removes is a silent pick, so an
    unrecognised stored value must not quietly become one by another route.

    The legacy harness-name aliases (``claude`` / ``codex`` / ...) are deliberately
    NOT valid defaults, even though ``stage_project`` still tolerates them on an
    explicit call (BE-9554). Tolerance is owed to callers registered against the
    old surface; a preference written today has no such claim on it.
    """
    if setting_value in VALID_EXECUTION_MODES:
        return str(setting_value)
    return ""
