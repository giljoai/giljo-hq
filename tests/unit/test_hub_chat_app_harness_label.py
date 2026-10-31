# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace

from api.endpoints.mcp_tools._harness import _hub_harness
from giljo_mcp.harness_resolver import (
    GENERIC_HARNESS,
    HARNESS_CLAUDE_CODE,
    HARNESS_CODEX,
    HUB_SURFACE_CHATGPT,
    HUB_SURFACE_CLAUDE,
    HUB_SURFACE_HERMES,
    hub_participant_harness,
)


def test_chat_apps_get_their_own_hub_label() -> None:
    assert hub_participant_harness(GENERIC_HARNESS, "Anthropic/ClaudeAI") == HUB_SURFACE_CLAUDE
    assert hub_participant_harness(GENERIC_HARNESS, "openai-mcp") == HUB_SURFACE_CHATGPT
    assert hub_participant_harness(GENERIC_HARNESS, "openai-mcp (ChatGPT)") == HUB_SURFACE_CHATGPT
    assert hub_participant_harness(GENERIC_HARNESS, "openai-mcp (Codex)") == HUB_SURFACE_CHATGPT


def test_a_detected_harness_always_wins() -> None:
    assert hub_participant_harness(HARNESS_CODEX, "openai-mcp") == HARNESS_CODEX
    assert hub_participant_harness(HARNESS_CLAUDE_CODE, "Anthropic/ClaudeAI") == HARNESS_CLAUDE_CODE


def test_the_hermes_support_agent_is_named() -> None:
    assert hub_participant_harness(GENERIC_HARNESS, "hermes-agent") == HUB_SURFACE_HERMES


def test_unknown_or_missing_clients_stay_generic() -> None:
    assert hub_participant_harness(GENERIC_HARNESS, "some-new-client") == GENERIC_HARNESS
    assert hub_participant_harness(None, None) == GENERIC_HARNESS
    assert hub_participant_harness(GENERIC_HARNESS, "  ") == GENERIC_HARNESS


def _ctx(client_name: str | None) -> SimpleNamespace:
    state = {} if client_name is None else {"mcp_client_name": client_name}
    request = SimpleNamespace(scope={"state": state})
    return SimpleNamespace(
        session=SimpleNamespace(client_params=None),
        request_context=SimpleNamespace(request=request),
    )


def test_the_mcp_boundary_reads_the_stamped_client_name() -> None:
    assert _hub_harness(_ctx("Anthropic/ClaudeAI")) == HUB_SURFACE_CLAUDE
    assert _hub_harness(_ctx("openai-mcp")) == HUB_SURFACE_CHATGPT
    assert _hub_harness(_ctx(None)) == GENERIC_HARNESS
