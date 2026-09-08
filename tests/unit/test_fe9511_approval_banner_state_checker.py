# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9511 durable guard: an approval banner_state missing from the
frontend's APPROVAL_BANNER_STATE_TEXT map must FAIL A TEST, not render as a
silent fallback.

Sibling of tests/unit/test_fe9501d_banner_allowlist_checker.py, adapted for
the approval banner's shape: FE-9511 deliberately does NOT route the approval
banner through the `system.*` notification family that checker covers (see
The decided design -- an approval is
one row per pending request, not a per-tenant singleton, so forcing it into
that family would be shape violence). This checker instead diffs the closed
Python enum against the Vue layer's own closed rendering map.

Static (regex) by design: this must catch the gap at review/CI time, not at
runtime when a state silently falls back to the decision_needed default text.
"""

import re
from pathlib import Path

from giljo_mcp.schemas.user_approval import VALID_APPROVAL_BANNER_STATES


REPO_ROOT = Path(__file__).resolve().parents[2]
# Guardrail 1 (800-line cap) moved the canned-text map out of
# SystemStatusBanner.vue and into this composable -- update this path if it
# moves again, not the assertion it feeds.
_APPROVAL_BANNER_STATE_SOURCE = REPO_ROOT / "frontend" / "src" / "composables" / "useApprovalBannerState.js"


def _rendered_approval_banner_states() -> set[str]:
    """Extract the keys of `APPROVAL_BANNER_STATE_TEXT = { key: '...', ... }`."""
    text = _APPROVAL_BANNER_STATE_SOURCE.read_text()
    match = re.search(
        r"const APPROVAL_BANNER_STATE_TEXT = \{(.*?)\n\}",
        text,
        re.DOTALL,
    )
    assert match, (
        "could not find `const APPROVAL_BANNER_STATE_TEXT = {...}` in "
        "useApprovalBannerState.js -- this checker is stale against a "
        "refactor and needs updating, not deleting"
    )
    body = match.group(1)
    body = re.sub(r"//.*", "", body)  # strip line comments before key extraction
    return set(re.findall(r"(\w+):\s*'", body))


def test_every_valid_approval_banner_state_has_canned_text_in_the_vue_component():
    """Every state in VALID_APPROVAL_BANNER_STATES must have a rendering entry.

    A state the backend can emit but the frontend map does not cover would
    silently fall back to the decision_needed text (see approvalMessage's `||`
    fallback) -- misleading copy shown for the wrong reason, never a blank
    banner, which is exactly why this needs a static test rather than trusting
    someone to notice at runtime.
    """
    rendered = _rendered_approval_banner_states()
    missing = VALID_APPROVAL_BANNER_STATES - rendered
    assert not missing, (
        f"backend VALID_APPROVAL_BANNER_STATES has state(s) {sorted(missing)} "
        "with no entry in useApprovalBannerState.js's APPROVAL_BANNER_STATE_TEXT "
        "-- add the canned text there before this state can ship."
    )


def test_the_scan_itself_finds_something():
    """Sanity: an empty result means the regex broke, not that the map is empty."""
    assert _rendered_approval_banner_states(), "AST/regex scan found zero rendered approval banner states"
