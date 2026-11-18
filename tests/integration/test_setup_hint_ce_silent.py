# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.api.test_mcp_session import _seed_api_key
from tests.helpers.mcp_http_wire import Agent, mcp_wire, model_text


pytestmark = pytest.mark.asyncio


async def test_ce_replies_carry_no_hint_over_the_wire(db_manager):
    from api.endpoints.mcp_tools import _announcement_hook

    prior = (_announcement_hook._provider, _announcement_hook._hint_provider)
    _announcement_hook.install_announcement_provider(None)
    _announcement_hook.install_setup_hint_provider(None)
    _announcement_hook.reset_told_sessions()
    key, _ = await _seed_api_key(db_manager)
    try:
        async with mcp_wire(db_manager) as wire:
            agent = await Agent(wire, key).connect()
            first = json.loads(model_text(await agent.call("list_threads")))
            setup = json.loads(model_text(await agent.call("giljo_setup", {"platform": "claude_code"})))
    finally:
        _announcement_hook.install_announcement_provider(prior[0])
        _announcement_hook.install_setup_hint_provider(prior[1])
        _announcement_hook.reset_told_sessions()
    assert set(first["_meta"]) == {"skills_version"}, "the call ran and the _meta is exactly today's"
    assert "setup_hint" not in setup.get("_meta", {})
    assert "setup hint" not in json.dumps(setup).lower()


async def test_without_a_provider_the_hook_does_no_work_at_all():
    from api.endpoints.mcp_tools import _announcement_hook

    def _must_not_run(_ctx):
        raise AssertionError("CE must not resolve the caller")

    prior = (_announcement_hook._provider, _announcement_hook._hint_provider)
    _announcement_hook.install_announcement_provider(None)
    _announcement_hook.install_setup_hint_provider(None)
    try:
        assert await _announcement_hook.first_reply_meta(None, "tk", _must_not_run) == {}
        reply = {"ok": True}
        assert await _announcement_hook.add_setup_hint(reply, "tk", "u") is reply
        assert reply == {"ok": True}
    finally:
        _announcement_hook.install_announcement_provider(prior[0])
        _announcement_hook.install_setup_hint_provider(prior[1])


async def test_a_hint_provider_alone_rides_the_first_reply_through_the_hook():
    from api.endpoints.mcp_tools import _announcement_hook

    async def hint(tenant_key, user_id):
        return "hello"

    prior = (_announcement_hook._provider, _announcement_hook._hint_provider)
    _announcement_hook.install_announcement_provider(None)
    _announcement_hook.install_setup_hint_provider(hint)
    _announcement_hook.reset_told_sessions()
    ctx = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers={"mcp-session-id": "s"})))
    try:
        assert await _announcement_hook.first_reply_meta(ctx, "tk", lambda _c: "u") == {"setup_hint": "hello"}
        assert await _announcement_hook.first_reply_meta(ctx, "tk", lambda _c: "u") == {}
    finally:
        _announcement_hook.install_announcement_provider(prior[0])
        _announcement_hook.install_setup_hint_provider(prior[1])
        _announcement_hook.reset_told_sessions()


async def test_ce_create_replies_carry_no_link(db_manager):
    from api.endpoints.mcp_tools import _announcement_hook

    prior = _announcement_hook._view_link_builder
    _announcement_hook.install_view_link_builder(None)
    key, _ = await _seed_api_key(db_manager)
    try:
        async with mcp_wire(db_manager) as wire:
            agent = await Agent(wire, key).connect()
            created = json.loads(model_text(await agent.call("create_product", {"name": "CE product"})))
    finally:
        _announcement_hook.install_view_link_builder(prior)
    assert created["success"] is True
    assert "view_url" not in created
    assert "See it here" not in json.dumps(created)


async def test_ce_static_tools_and_errors_are_untouched_over_the_wire(db_manager):
    from api.endpoints.mcp_tools import _announcement_hook

    prior = (_announcement_hook._provider, _announcement_hook._hint_provider)
    _announcement_hook.install_announcement_provider(None)
    _announcement_hook.install_setup_hint_provider(None)
    key, _ = await _seed_api_key(db_manager)
    try:
        async with mcp_wire(db_manager) as wire:
            agent = await Agent(wire, key).connect()
            health = json.loads(model_text(await agent.call("health_check")))
            guide = json.loads(model_text(await agent.call("get_giljo_guide")))
            error = await agent.call_unchecked("list_projects")
    finally:
        _announcement_hook.install_announcement_provider(prior[0])
        _announcement_hook.install_setup_hint_provider(prior[1])
        _announcement_hook.reset_told_sessions()
    assert "_meta" not in health and "_meta" not in guide
    assert model_text(error) == (
        "Error executing tool list_projects: You have no product yet. Create one first with create_product, then try again."
    )
