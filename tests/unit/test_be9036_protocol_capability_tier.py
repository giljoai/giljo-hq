# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from mcp.types import ClientCapabilities, ElicitationCapability

from api.endpoints.mcp_tools._harness import (
    _detected_harness,
    _protocol_capabilities,
    get_session_capabilities,
)


def _ctx(
    *,
    declared: ClientCapabilities | None = None,
    probe_result: bool = False,
    client_name: str | None = None,
    scope_state: dict | None = None,
):
    client_info = SimpleNamespace(name=client_name, version="1.0.0") if client_name is not None else None
    session = SimpleNamespace(client_params=SimpleNamespace(client_info=client_info))
    session.check_client_capability = lambda cap: probe_result
    request = SimpleNamespace(scope={"state": scope_state}) if scope_state is not None else None
    ctx = SimpleNamespace(session=session, request_context=SimpleNamespace(request=request))
    if declared is not None:
        ctx.client_capabilities = declared
    return ctx


class TestProtocolTierEngagesOnlyOnRealCapabilities:

    def test_real_client_capabilities_are_read(self):
        declared = ClientCapabilities(elicitation=ElicitationCapability())
        assert _protocol_capabilities(_ctx(declared=declared)) is declared

    def test_absent_attribute_yields_no_protocol_tier(self):
        assert _protocol_capabilities(_ctx()) is None

    def test_a_magicmock_ctx_does_not_fake_a_protocol_tier(self):
        assert _protocol_capabilities(MagicMock()) is None

    def test_a_raising_ctx_never_propagates(self):
        exploding = MagicMock()
        type(exploding).client_capabilities = property(lambda _self: (_ for _ in ()).throw(RuntimeError("no ctx")))
        assert _protocol_capabilities(exploding) is None


class TestTasksCapabilityIsReadOffTheProtocolAxis:

    def test_first_class_tasks_field_is_detected(self):
        caps = get_session_capabilities(_ctx(declared=ClientCapabilities(tasks={}), probe_result=False))
        assert caps["tasks"] is True

    def test_pre_ga_experimental_spelling_still_counts(self):
        declared = ClientCapabilities(experimental={"io.modelcontextprotocol/tasks": {}})
        caps = get_session_capabilities(_ctx(declared=declared, probe_result=False))
        assert caps["tasks"] is True

    def test_a_client_declaring_neither_is_not_credited_with_tasks(self):
        declared = ClientCapabilities(elicitation=ElicitationCapability())
        caps = get_session_capabilities(_ctx(declared=declared, probe_result=True))
        assert caps["tasks"] is False


class TestElicitationReadIsUnchangedInMeaning:

    @pytest.mark.parametrize(
        ("declared", "expected"),
        [
            (ClientCapabilities(), False),
            (ClientCapabilities(elicitation=ElicitationCapability()), True),
            (ClientCapabilities(experimental={"other": {}}), False),
            (ClientCapabilities(elicitation=ElicitationCapability(), tasks={}), True),
        ],
    )
    def test_protocol_read_matches_the_probe_it_replaces(self, declared, expected):
        caps = get_session_capabilities(_ctx(declared=declared, probe_result=not expected))
        assert caps["elicitation"] is expected


class TestLegacyTierStillServesTheLiveFleet:

    def test_probe_answers_when_no_capabilities_were_declared(self):
        assert get_session_capabilities(_ctx(probe_result=True))["elicitation"] is True
        assert get_session_capabilities(_ctx(probe_result=False))["elicitation"] is False

    def test_live_client_info_resolves_the_harness(self):
        assert _detected_harness(_ctx(client_name="claude-code")) == "claude-code"

    def test_fleet_render_path_resolves_from_the_persisted_stamp(self):
        ctx = _ctx(client_name=None, scope_state={"resolved_harness": "claude-code"})
        assert _detected_harness(ctx) == "claude-code", (
            "the live fleet's harness no longer resolves on the render path -- a "
            "claude-code CLI would fall back to the generic '<your-harness>' ladder "
            "(BE-9035d FINDING #4)."
        )

    def test_nothing_anywhere_degrades_to_generic_and_never_raises(self):
        caps = get_session_capabilities(_ctx())
        assert caps == {"elicitation": False, "tasks": False, "harness": "generic", "preset": None}
