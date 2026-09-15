# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations


BANNED_AGENT_PROSE_TOKENS: tuple[tuple[str, str], ...] = (
    (
        "acknowledge_closeout_todo",
        "retired complete_job flag (BE-9012b) — the closeout TODO auto-completes structurally; "
        "the server accepts-and-ignores the flag, so prose teaching it gives no-op advice",
    ),
    (
        "acknowledge_messages_on_complete",
        "retired complete_job flag (BE-9012b) — the messages gate blocks only on genuine "
        "action-required posts; there is no drain-bypass flag",
    ),
    (
        "claude_code_cli",
        "legacy execution-mode token (BE-9035c collapsed 6 modes onto 'multi_terminal' + 'subagent')",
    ),
    (
        "codex_cli",
        "legacy execution-mode token (BE-9035c) — canonical modes are 'multi_terminal' and 'subagent'",
    ),
    (
        "gemini_cli",
        "legacy execution-mode token (BE-9035c) — canonical modes are 'multi_terminal' and 'subagent'",
    ),
    (
        "antigravity_cli",
        "legacy execution-mode token (BE-9035c) — canonical modes are 'multi_terminal' and 'subagent'",
    ),
)


TOOL_PROSE_SURVIVORS: frozenset[tuple[str, str]] = frozenset(
    {
        ("complete_job", "acknowledge_closeout_todo"),
        ("complete_job", "acknowledge_messages_on_complete"),
        ("write_memory_entry", "acknowledge_closeout_todo"),
        ("giljo_setup", "gemini_cli"),
        ("giljo_setup", "codex_cli"),
        ("giljo_setup", "antigravity_cli"),
    }
)
