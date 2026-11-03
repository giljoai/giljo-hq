# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from api.endpoints.mcp_tools import _harness
from giljo_mcp.harness_resolver import (
    GENERIC_HARNESS,
    HUB_SURFACE_CHATGPT,
    HUB_SURFACE_CLAUDE,
    hub_surface_from_app_name,
)


def _ctx(state: dict):
    request = SimpleNamespace(scope={"state": state})
    return SimpleNamespace(request_context=SimpleNamespace(request=request), session=None)


@pytest.mark.parametrize(
    ("app_name", "expected"),
    [
        ("ChatGPT", HUB_SURFACE_CHATGPT),
        ("Claude", HUB_SURFACE_CLAUDE),
        ("Claude Code", None),
        ("Acme", None),
        (None, None),
    ],
)
def test_app_name_maps_only_the_hosted_apps(app_name, expected):
    assert hub_surface_from_app_name(app_name) == expected


@pytest.fixture
def login_names(monkeypatch):
    names: dict[str, tuple[str | None, str | None]] = {}

    async def _lookup(db, *, tenant_key, family_id):
        return names.get(family_id, (None, None))

    @asynccontextmanager
    async def _session():
        yield object()

    monkeypatch.setattr("giljo_mcp.services.oauth_login_service.login_app_names", _lookup)
    monkeypatch.setattr("api.app_state.state.db_manager", SimpleNamespace(get_session_async=_session), raising=False)
    return names


@pytest.mark.asyncio
async def test_a_nameless_chatgpt_call_reads_as_chatgpt(login_names):
    login_names["fam-1"] = ("ChatGPT", None)
    ctx = _ctx({"oauth_family_id": "fam-1", "tenant_key": "tk"})
    assert await _harness._hub_harness_for_call(ctx) == HUB_SURFACE_CHATGPT


@pytest.mark.asyncio
async def test_the_last_reported_client_name_wins_over_the_app_name(login_names):
    login_names["fam-2"] = ("Some App", "Anthropic/ClaudeAI")
    ctx = _ctx({"oauth_family_id": "fam-2", "tenant_key": "tk"})
    assert await _harness._hub_harness_for_call(ctx) == HUB_SURFACE_CLAUDE


@pytest.mark.asyncio
async def test_no_login_stays_generic(login_names):
    assert await _harness._hub_harness_for_call(_ctx({"tenant_key": "tk"})) == GENERIC_HARNESS


@pytest.mark.asyncio
async def test_a_named_call_needs_no_lookup(login_names):
    login_names["fam-3"] = ("ChatGPT", None)
    ctx = _ctx({"mcp_client_name": "hermes-agent", "oauth_family_id": "fam-3", "tenant_key": "tk"})
    assert await _harness._hub_harness_for_call(ctx) == "hermes"
