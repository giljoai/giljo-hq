# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


HARNESS_CLAUDE_CODE = "claude-code"
HARNESS_CODEX = "codex"
HARNESS_OPENCODE = "opencode"
GENERIC_HARNESS = "generic"


_HARNESS_BY_CLIENT_NAME: dict[str, str] = {
    "claude-code": HARNESS_CLAUDE_CODE,
    "codex-mcp-client": HARNESS_CODEX,
    "opencode": HARNESS_OPENCODE,
}


_KNOWN_GENERIC_CLIENT_NAMES: frozenset[str] = frozenset(
    {
        "Anthropic/ClaudeAI",
        "Anthropic/Toolbox",
        "openai-mcp",
        "openai-mcp (ChatGPT)",
        "openai-mcp (Codex)",
        "opencode-check",
    }
)


_PRESET_WEB_SANDBOX = "web_sandbox"
_PRESET_CHAT = "chat"


_PRESET_BY_CLIENT_NAME: dict[str, str] = {
    "openai-mcp": _PRESET_CHAT,
    "openai-mcp (ChatGPT)": _PRESET_CHAT,
    "openai-mcp (Codex)": _PRESET_WEB_SANDBOX,
}


def preset_from_client_info(name: str | None, version: str | None = None) -> str | None:
    return _PRESET_BY_CLIENT_NAME.get((name or "").strip())


def harness_from_client_info(name: str | None, version: str | None = None) -> str:
    key = (name or "").strip()
    if not key:
        return GENERIC_HARNESS
    harness = _HARNESS_BY_CLIENT_NAME.get(key)
    if harness is not None:
        return harness
    if key in _KNOWN_GENERIC_CLIENT_NAMES:
        return GENERIC_HARNESS
    logger.info(
        "[harness-detect] unrecognized MCP clientInfo name=%r version=%r -> generic "
        "(add a table row if this is a real harness)",
        key,
        (version or "").strip() or None,
    )
    return GENERIC_HARNESS


def _detected_harness_from_session(session: object | None) -> str | None:
    if session is None:
        return None
    data = getattr(session, "session_data", None)
    if isinstance(data, dict):
        stamped = data.get("resolved_harness")
        if isinstance(stamped, str) and stamped:
            return stamped
    if isinstance(session, dict):
        for candidate_key in ("resolved_harness", "harness"):
            value = session.get(candidate_key)
            if isinstance(value, str) and value:
                return value
    return None
