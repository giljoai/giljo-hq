# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9036 -- the two-tier capability read, and the legacy tier that serves the fleet.

Companion to ``tests/integration/test_be9036_capability_axis_by_era.py``. That file
measures what the SDK delivers per protocol era over real HTTP; this one pins how
``_harness`` behaves given each of those two worlds:

* PROTOCOL tier -- a 2026-07-28 client's declared ``ClientCapabilities`` are read
  directly off the request (``ctx.client_capabilities``).
* LEGACY tier -- everything else falls back to the ``check_client_capability`` probe and
  to the clientInfo/persisted-stamp harness resolution, which is what the live
  claude-code fleet uses on every call.

The fleet-path test is the one with teeth: it fails if the persisted-stamp fallback is
deleted, which is the museum-rule guard on the three retained workaround sites.

Edition Scope: Both.
"""

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
    """Build a ctx double spanning all three axes the capability read consults.

    ``declared`` models the 2026-07-28 protocol envelope; ``probe_result`` models the
    legacy ``check_client_capability`` answer; ``client_name`` models a live clientInfo
    (``None`` = the stateless_http drop); ``scope_state`` models the ASGI state the
    middleware stamps (``None`` = no HTTP request at all, i.e. in-memory transport).
    """
    client_info = SimpleNamespace(name=client_name, version="1.0.0") if client_name is not None else None
    session = SimpleNamespace(client_params=SimpleNamespace(client_info=client_info))
    session.check_client_capability = lambda cap: probe_result
    request = SimpleNamespace(scope={"state": scope_state}) if scope_state is not None else None
    ctx = SimpleNamespace(session=session, request_context=SimpleNamespace(request=request))
    if declared is not None:
        ctx.client_capabilities = declared
    return ctx


class TestProtocolTierEngagesOnlyOnRealCapabilities:
    """``_protocol_capabilities`` answers "did the SDK hand us capabilities?" -- a fact."""

    def test_real_client_capabilities_are_read(self):
        declared = ClientCapabilities(elicitation=ElicitationCapability())
        assert _protocol_capabilities(_ctx(declared=declared)) is declared

    def test_absent_attribute_yields_no_protocol_tier(self):
        """The 2025-era shape: nothing declared, so the legacy tier must answer."""
        assert _protocol_capabilities(_ctx()) is None

    def test_a_magicmock_ctx_does_not_fake_a_protocol_tier(self):
        """The isinstance guard is load-bearing, not decorative.

        ``MagicMock`` returns a truthy Mock for ANY attribute, so an unguarded
        ``ctx.client_capabilities.elicitation`` would report support for every
        capability on every mock-based caller in the suite. Guarding on the real type
        makes the tier engage only when the SDK genuinely supplied capabilities.
        """
        assert _protocol_capabilities(MagicMock()) is None

    def test_a_raising_ctx_never_propagates(self):
        """Capability detection is a render hint; it must never raise into a tool."""
        exploding = MagicMock()
        type(exploding).client_capabilities = property(lambda _self: (_ for _ in ()).throw(RuntimeError("no ctx")))
        assert _protocol_capabilities(exploding) is None


class TestTasksCapabilityIsReadOffTheProtocolAxis:
    """The defect BE-9036 fixes: a GA client's tasks support was reported as absent."""

    def test_first_class_tasks_field_is_detected(self):
        """SDK 2.0 promoted tasks to a real field; the pre-GA experimental probe missed it.

        Before this change the only tasks signal was
        ``check_client_capability(ClientCapabilities(experimental={...tasks: {}}))``,
        which returns False for a client declaring the first-class field -- a false
        negative on exactly the GA clients the capability axis exists to serve.
        """
        caps = get_session_capabilities(_ctx(declared=ClientCapabilities(tasks={}), probe_result=False))
        assert caps["tasks"] is True

    def test_pre_ga_experimental_spelling_still_counts(self):
        """Widening, not replacing: a client using the old spelling keeps working."""
        declared = ClientCapabilities(experimental={"io.modelcontextprotocol/tasks": {}})
        caps = get_session_capabilities(_ctx(declared=declared, probe_result=False))
        assert caps["tasks"] is True

    def test_a_client_declaring_neither_is_not_credited_with_tasks(self):
        """The floor -- and the guard against the SDK's vacuously-true tasks probe.

        ``Connection.check_capability`` has no ``tasks`` branch at all, so a
        tasks-shaped probe matches everything. Reading the declared capability is what
        keeps a client that never mentioned tasks from being reported as supporting
        them.
        """
        declared = ClientCapabilities(elicitation=ElicitationCapability())
        caps = get_session_capabilities(_ctx(declared=declared, probe_result=True))
        assert caps["tasks"] is False


class TestElicitationReadIsUnchangedInMeaning:
    """The swap is behaviour-preserving: check_capability's branch IS this predicate."""

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
    """DoD 2: a 2025-era client must still resolve correctly. It has no protocol tier."""

    def test_probe_answers_when_no_capabilities_were_declared(self):
        """With no protocol axis, the original probe is still the answer -- both ways."""
        assert get_session_capabilities(_ctx(probe_result=True))["elicitation"] is True
        assert get_session_capabilities(_ctx(probe_result=False))["elicitation"] is False

    def test_live_client_info_resolves_the_harness(self):
        """The initialize request and the in-memory transport: clientInfo is readable."""
        assert _detected_harness(_ctx(client_name="claude-code")) == "claude-code"

    def test_fleet_render_path_resolves_from_the_persisted_stamp(self):
        """THE fleet case, and the museum-rule guard on the three retained workarounds.

        This is a live claude-code ``tools/call`` exactly as measured over the wire: no
        protocol capabilities, no live clientInfo (``stateless_http`` dropped it), only
        the harness the middleware persisted at initialize and stamped onto ASGI state.

        If the persisted-stamp fallback is ever deleted as "made redundant by the SDK 2.0
        capability axis", this test goes red -- which is the point. It is the executable
        form of the retention argument written into ``_persisted_harness``,
        ``_stamp_resolved_harness`` and ``_client_info_patch``.
        """
        ctx = _ctx(client_name=None, scope_state={"resolved_harness": "claude-code"})
        assert _detected_harness(ctx) == "claude-code", (
            "the live fleet's harness no longer resolves on the render path -- a "
            "claude-code CLI would fall back to the generic '<your-harness>' ladder "
            "(BE-9035d FINDING #4)."
        )

    def test_nothing_anywhere_degrades_to_generic_and_never_raises(self):
        """The fail-safe floor is preserved across both tiers."""
        caps = get_session_capabilities(_ctx())
        assert caps == {"elicitation": False, "tasks": False, "harness": "generic", "preset": None}
