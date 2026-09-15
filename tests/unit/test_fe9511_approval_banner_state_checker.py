# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import re
from pathlib import Path

from giljo_mcp.schemas.user_approval import VALID_APPROVAL_BANNER_STATES


REPO_ROOT = Path(__file__).resolve().parents[2]
_APPROVAL_BANNER_STATE_SOURCE = REPO_ROOT / "frontend" / "src" / "composables" / "useApprovalBannerState.js"


def _rendered_approval_banner_states() -> set[str]:
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
    body = re.sub(r"//.*", "", body)
    return set(re.findall(r"(\w+):\s*'", body))


def test_every_valid_approval_banner_state_has_canned_text_in_the_vue_component():
    rendered = _rendered_approval_banner_states()
    missing = VALID_APPROVAL_BANNER_STATES - rendered
    assert not missing, (
        f"backend VALID_APPROVAL_BANNER_STATES has state(s) {sorted(missing)} "
        "with no entry in useApprovalBannerState.js's APPROVAL_BANNER_STATE_TEXT "
        "-- add the canned text there before this state can ship."
    )


def test_the_scan_itself_finds_something():
    assert _rendered_approval_banner_states(), "AST/regex scan found zero rendered approval banner states"
