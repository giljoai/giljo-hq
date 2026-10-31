# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import re


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


CIMD_CLIENT_HARNESSES: dict[str, str] = {
    "https://claude.ai/oauth/claude-code-client-metadata": HARNESS_CLAUDE_CODE,
    "https://claude.ai/oauth/mcp-oauth-client-metadata": GENERIC_HARNESS,
    "https://chatgpt.com/oauth/client.json": GENERIC_HARNESS,
    "https://chatgpt.com/oauth/codex/client.json": HARNESS_CODEX,
    "https://vscode.dev/oauth/client-metadata.json": GENERIC_HARNESS,
    "https://insiders.vscode.dev/oauth/client-metadata.json": GENERIC_HARNESS,
    "https://opencode.ai/oauth/opencode/client.json": HARNESS_OPENCODE,
    "https://cursor.com/oauth/mcp-client.json": GENERIC_HARNESS,
}

CIMD_CLIENT_HARNESS_PATTERNS: dict[str, str] = {
    "https://chatgpt.com/oauth/{callback_id}/client.json": GENERIC_HARNESS,
    "https://chatgpt.com/oauth/codex/{callback_id}/client.json": HARNESS_CODEX,
}
_CALLBACK_ID = r"[A-Za-z0-9._~-]+"


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


def harness_from_oauth_client_id(client_id: str | None) -> str | None:
    if not client_id:
        return None
    exact = CIMD_CLIENT_HARNESSES.get(client_id)
    if exact is not None:
        return exact
    for template, harness in CIMD_CLIENT_HARNESS_PATTERNS.items():
        regex = re.escape(template).replace(re.escape("{callback_id}"), _CALLBACK_ID)
        if re.fullmatch(regex, client_id):
            return harness
    return None


def harness_for_connection(client_info: dict | None, oauth_client_id: str | None) -> str:
    info = client_info or {}
    from_cimd = harness_from_oauth_client_id(oauth_client_id)
    if from_cimd and from_cimd != GENERIC_HARNESS:
        return from_cimd
    return harness_from_client_info(info.get("name"), info.get("version"))


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


HUB_SURFACE_CLAUDE = "claude"
HUB_SURFACE_CHATGPT = "chatgpt"
HUB_SURFACE_HERMES = "hermes"
_HUB_SURFACE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("Anthropic/", HUB_SURFACE_CLAUDE),
    ("openai-mcp", HUB_SURFACE_CHATGPT),
    ("hermes-agent", HUB_SURFACE_HERMES),
)


def hub_participant_harness(detected: str | None, client_name: str | None) -> str:
    if detected and detected != GENERIC_HARNESS:
        return detected
    name = (client_name or "").strip()
    for prefix, surface in _HUB_SURFACE_PREFIXES:
        if name.startswith(prefix):
            return surface
    return GENERIC_HARNESS
