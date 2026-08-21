# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Inline approval overlay -- server-side logic (BE-6038, re-targeted by BE-8003l).

BE-6038 built this against ``ctx.elicit()``, the server-initiated elicitation
channel, behind a default-OFF ``GILJO_INLINE_APPROVAL_ELICIT`` flag because the
transport could not carry that round-trip ("constraint C1"). BE-8003l re-targets
the same behaviour onto MCP 2026-07-28's multi-round-trip: round 1 returns an
``InputRequiredResult``, round 2 arrives as a retry carrying ``request_state`` and
``input_responses``. **Every scenario BE-6038 covered is still covered here** --
same guarantees, different channel -- and each re-targeted test says in its own
docstring what it used to assert and why that is no longer true.

The invariants that did NOT change, and are the reason this file exists:
decide-convergence goes through the EXISTING ``UserApprovalService.mark_decided``
(no second write path), and EVERY miss leaves today's async ``awaiting_user``
behaviour intact.

Parallel-safe: no DB, no module-level mutable state; the kill switch is toggled
with ``monkeypatch.setenv`` and all collaborators are mocked.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp_types import InputRequiredResult

from api.endpoints.mcp_tools._inline_approval import (
    maybe_offer_approval_inline,
    resolve_pending_inline_approval,
)
from giljo_mcp.exceptions import ValidationError


_KILL_SWITCH = "GILJO_MRTR_APPROVAL"
_OPTIONS = [{"id": "approve", "label": "Approve"}, {"id": "reject", "label": "Reject"}]
_PENDING = {"approval_id": "ap-1", "status": "pending"}
_STATE = '{"kind": "be8003l.approval", "approval_id": "ap-1"}'
_MODERN = "2026-07-28"
_LEGACY = "2025-11-25"


def _capable_ctx(*, version: str = _MODERN, elicitation: bool = True):
    """A round-1 context: negotiated era + declared capabilities, no retry state.

    ``SimpleNamespace`` rather than ``MagicMock`` on purpose -- a MagicMock returns
    a truthy Mock for EVERY attribute, so a capability probe against one reports
    support that was never declared and the gate would look like it works when it
    does not.
    """
    capabilities = SimpleNamespace(elicitation=object()) if elicitation else SimpleNamespace(elicitation=None)
    return SimpleNamespace(
        protocol_version=version,
        client_capabilities=capabilities,
        request_state=None,
        input_responses=None,
    )


def _retry_ctx(*, action: str = "accept", choice: str = "approve", state: str | None = _STATE, answered: bool = True):
    """A round-2 context: the echoed (already unsealed) state plus the client's answer."""
    responses = None
    if answered:
        content = {"choice": choice} if action == "accept" else None
        responses = {"giljo_approval": SimpleNamespace(action=action, content=content)}
    return SimpleNamespace(
        protocol_version=_MODERN,
        client_capabilities=SimpleNamespace(elicitation=object()),
        request_state=state,
        input_responses=responses,
    )


def _wire_accessor(monkeypatch, *, mark_decided: AsyncMock) -> AsyncMock:
    """Point the inline-decide helpers at a mocked tool accessor + tenant/user resolvers."""
    accessor = MagicMock()
    accessor._user_approval_service.mark_decided = mark_decided
    monkeypatch.setattr("api.endpoints.mcp_tools._base._get_tool_accessor", lambda: accessor)
    monkeypatch.setattr("api.endpoints.mcp_tools._base._resolve_tenant", lambda ctx: "tenant-1")
    monkeypatch.setattr("api.endpoints.mcp_tools._base._resolve_user_id", lambda ctx: "user-9")
    return mark_decided


# ---------------------------------------------------------------------------
# Round 1 -- who gets offered the inline approval
# ---------------------------------------------------------------------------


def test_kill_switch_off_returns_unchanged_and_offers_nothing(monkeypatch):
    """Was: the default-OFF GILJO_INLINE_APPROVAL_ELICIT flag suppressed the overlay.

    Now inverted by design (BE-8003l DoD 3): the feature is gated STRUCTURALLY on a
    detectable connection property, so the env var is an operator kill switch that
    defaults to ON rather than a flag that defaults to OFF. Same assertion,
    opposite default.
    """
    monkeypatch.setenv(_KILL_SWITCH, "off")
    out = maybe_offer_approval_inline(_capable_ctx(), dict(_PENDING), reason="r", options=_OPTIONS)
    assert out == _PENDING


def test_ctx_none_returns_unchanged(monkeypatch):
    monkeypatch.delenv(_KILL_SWITCH, raising=False)
    out = maybe_offer_approval_inline(None, dict(_PENDING), reason="r", options=_OPTIONS)
    assert out == _PENDING


def test_no_client_capability_falls_back(monkeypatch):
    monkeypatch.delenv(_KILL_SWITCH, raising=False)
    out = maybe_offer_approval_inline(_capable_ctx(elicitation=False), dict(_PENDING), reason="r", options=_OPTIONS)
    assert out == _PENDING


def test_legacy_era_falls_back_even_when_the_client_declares_elicitation(monkeypatch):
    """BE-8003l: the era gate, which BE-6038 had no reason to have.

    A 2025-era client CAN declare elicitation, and on that revision an
    ``InputRequiredResult`` is not a legal tools/call result -- the SDK answers
    -32603. The live fleet is exactly this client, so a capability-only gate would
    have failed every production approval.
    """
    monkeypatch.delenv(_KILL_SWITCH, raising=False)
    out = maybe_offer_approval_inline(_capable_ctx(version=_LEGACY), dict(_PENDING), reason="r", options=_OPTIONS)
    assert out == _PENDING


def test_unknown_protocol_revision_fails_closed(monkeypatch):
    monkeypatch.delenv(_KILL_SWITCH, raising=False)
    out = maybe_offer_approval_inline(_capable_ctx(version="1999-01-01"), dict(_PENDING), reason="r", options=_OPTIONS)
    assert out == _PENDING


def test_capable_client_is_offered_the_choice(monkeypatch):
    """Was: ``ctx.elicit`` was awaited with a generated schema.

    Now the same offer is a RETURNED ``InputRequiredResult`` -- the 2026-07-28
    channel -- carrying the caller's own option ids as a spec-valid primitive enum.
    """
    monkeypatch.delenv(_KILL_SWITCH, raising=False)
    out = maybe_offer_approval_inline(_capable_ctx(), dict(_PENDING), reason="please choose", options=_OPTIONS)

    assert isinstance(out, InputRequiredResult)
    assert out.result_type == "input_required"
    request = out.input_requests["giljo_approval"]
    assert request.method == "elicitation/create"
    assert "please choose" in request.params.message
    choice = request.params.requested_schema["properties"]["choice"]
    assert choice["type"] == "string", "the spec admits no $ref in an elicitation schema"
    assert choice["enum"] == ["approve", "reject"]
    assert choice["enumNames"] == ["Approve", "Reject"]
    assert out.request_state and "ap-1" in out.request_state


def test_offer_build_failure_falls_back(monkeypatch):
    """Was: ``ctx.elicit`` raising (constraint C1's transport miss) fell back.

    That channel is gone; the equivalent miss is now the offer failing to build.
    The guarantee under test is unchanged: a failure here NEVER raises into the
    tool, and the caller keeps today's parked answer.
    """
    monkeypatch.delenv(_KILL_SWITCH, raising=False)
    monkeypatch.setattr(
        "api.endpoints.mcp_tools._inline_approval._build_input_required",
        MagicMock(side_effect=RuntimeError("boom")),
    )
    out = maybe_offer_approval_inline(_capable_ctx(), dict(_PENDING), reason="r", options=_OPTIONS)
    assert out == _PENDING


def test_non_pending_result_unchanged(monkeypatch):
    """Also covers the BE-6081 ORCHESTRATOR_ONLY_APPROVAL rejection: no row to offer."""
    monkeypatch.delenv(_KILL_SWITCH, raising=False)
    already = {"approval_id": "ap-2", "status": "decided"}
    assert maybe_offer_approval_inline(_capable_ctx(), dict(already), reason="r", options=_OPTIONS) == already

    rejection = {"success": False, "error": "ORCHESTRATOR_ONLY_APPROVAL"}
    assert maybe_offer_approval_inline(_capable_ctx(), dict(rejection), reason="r", options=_OPTIONS) == rejection


def test_empty_options_falls_back(monkeypatch):
    monkeypatch.delenv(_KILL_SWITCH, raising=False)
    assert maybe_offer_approval_inline(_capable_ctx(), dict(_PENDING), reason="r", options=[]) == _PENDING


# ---------------------------------------------------------------------------
# Round 2 -- settling the approval the retry is answering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_ordinary_call_is_not_treated_as_a_retry():
    """Returning None is what makes the caller dispatch normally.

    If this ever returned a dict on a first-round call, ``request_approval`` would
    stop creating approvals entirely.
    """
    assert await resolve_pending_inline_approval(_capable_ctx(), _OPTIONS) is None
    assert await resolve_pending_inline_approval(None, _OPTIONS) is None
    assert await resolve_pending_inline_approval(_retry_ctx(state='{"kind": "someone-else"}'), _OPTIONS) is None
    assert await resolve_pending_inline_approval(_retry_ctx(state="not json"), _OPTIONS) is None


@pytest.mark.asyncio
async def test_accept_routes_through_mark_decided(monkeypatch):
    mark = _wire_accessor(monkeypatch, mark_decided=AsyncMock(return_value=MagicMock()))

    out = await resolve_pending_inline_approval(_retry_ctx(), _OPTIONS)

    assert out["status"] == "decided"
    assert out["decided_option_id"] == "approve"
    assert out["surface"] == "inline"
    assert out["approval_id"] == "ap-1"
    mark.assert_awaited_once_with(tenant_key="tenant-1", approval_id="ap-1", option_id="approve", user_id="user-9")


@pytest.mark.asyncio
async def test_decline_leaves_pending_and_does_not_decide(monkeypatch):
    mark = _wire_accessor(monkeypatch, mark_decided=AsyncMock())
    out = await resolve_pending_inline_approval(_retry_ctx(action="decline"), _OPTIONS)
    assert out == _PENDING
    mark.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_retry_carrying_no_answer_stays_pending_and_does_not_re_ask(monkeypatch):
    """Stop-condition: an unanswered retry must converge, not loop.

    Re-offering here would let a client that cannot answer bounce forever.
    """
    mark = _wire_accessor(monkeypatch, mark_decided=AsyncMock())
    out = await resolve_pending_inline_approval(_retry_ctx(answered=False), _OPTIONS)
    assert out == _PENDING
    assert not isinstance(out, InputRequiredResult)
    mark.assert_not_awaited()


@pytest.mark.asyncio
async def test_dashboard_race_marks_decided_validationerror_falls_back(monkeypatch):
    """Concurrent dashboard decision -> mark_decided raises (not pending) -> stays pending."""
    mark = _wire_accessor(monkeypatch, mark_decided=AsyncMock(side_effect=ValidationError("not pending")))
    out = await resolve_pending_inline_approval(_retry_ctx(), _OPTIONS)
    assert out == _PENDING  # unchanged; gate already cleared elsewhere
    mark.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_choice_outside_the_callers_options_is_never_written(monkeypatch):
    """The client's answer is data, not instruction: it is checked against the
    caller's own option list before any write."""
    mark = _wire_accessor(monkeypatch, mark_decided=AsyncMock())
    out = await resolve_pending_inline_approval(_retry_ctx(choice="not-an-option"), _OPTIONS)
    assert out == _PENDING
    mark.assert_not_awaited()
