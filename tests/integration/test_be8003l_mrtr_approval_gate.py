# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-8003l item 1 -- ``request_approval`` offers an MRTR path to capable clients.

Why this file drives raw HTTP instead of the in-memory transport
===============================================================
The feature only exists on protocol revision 2026-07-28 (the "modern era"), and
``tests/helpers/mcp_session_fixture.create_connected_server_and_client_session``
cannot reach it: ``ClientSession.initialize()`` hardcodes the latest HANDSHAKE
revision, so every in-memory boundary test speaks 2025-11-25 and only that
(``test_inf9371_wire_revisions`` states this in its own docstring). So the
protocol axis comes from that file's ``wire_client()`` harness -- imported, not
copied, so the two cannot drift -- and the data axis (tenant + accessor bound to
the rolled-back session) comes from ``test_request_approval_mcp_transport``'s
fixture shape.

What is actually pinned
=======================
1. CAPABLE client (modern era + declared elicitation) -- round 1 answers
   ``resultType: input_required`` with a sealed ``requestState``; round 2
   carrying an accepted ``ElicitResult`` decides the approval through the SAME
   ``UserApprovalService.mark_decided`` the dashboard ``/decide`` endpoint uses,
   and leaves EXACTLY ONE approval row (round 2 re-enters the tool with
   byte-identical arguments -- the sealed envelope binds an args digest, so a
   second parked row is precisely the failure this design could produce if the
   ``request_state`` check ever moved below dispatch).
2. NON-CAPABLE client (modern era, no elicitation capability) -- unchanged:
   a plain dict, a parked ``awaiting_user`` row, no ``input_required``.
3. LEGACY client (2025-11-25) -- unchanged, AND specifically not an error.
   ``mcp_types.methods.serialize_server_result`` validates the result against the
   NEGOTIATED revision, and ``InputRequiredResult`` is not a legal ``tools/call``
   result before 2026-07-28: returning one there is a **-32603 Internal error**,
   measured. The live fleet is claude-code on a 2025-era revision, so this is the
   path every production approval takes today.
   Scope stated honestly: these legacy cases do NOT discriminate an era gate from
   a capability-only one -- verified by running that mutation, not assumed. Under
   our shipped ``stateless_http=True`` a legacy-negotiated request never surfaces
   ``client_capabilities`` at all, so both gates agree on every client shape
   reachable through this transport today. The era gate's teeth live in
   ``tests/unit/test_be6038_inline_approval_elicit.py``, whose contexts model the
   session-ful world where the two disagree. What these cases pin is the
   behaviour itself: the legacy fleet keeps today's answer.
4. Round 2 DECLINED / CANCELLED -- the approval stays pending for the dashboard.
5. Round 2 with state but NO responses -- stays pending and does NOT re-ask.
   A client that retries must converge; an unconditional re-ask is a loop.

Parallel-safe: no module-level mutable state; every fixture cleans up after
itself and all DB writes ride the rolled-back ``db_session``.

Edition Scope: Both.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.user_approval import UserApproval
from giljo_mcp.tenant import TenantManager

# Imported rather than re-implemented: one definition of the wire harness, so a
# transport-config change cannot leave this file passing against a shape we do
# not ship (both use production's own ``_STREAMABLE_HTTP_KWARGS``).
from tests.integration.test_inf9371_wire_revisions import _body, wire_client


pytestmark = pytest.mark.asyncio

_MODERN = "2026-07-28"
_LEGACY = "2025-11-25"

_OPTIONS = [{"id": "approve", "label": "Approve"}, {"id": "rework", "label": "Rework"}]


def _envelope(*, elicitation: bool) -> dict[str, Any]:
    """The modern era's reserved ``_meta`` keys, with or without elicitation.

    Under ``stateless_http`` these are the ONLY carrier of client capabilities --
    a 2025-era handshake's declaration does not survive to the ``tools/call``.
    """
    caps: dict[str, Any] = {"elicitation": {"form": {}}} if elicitation else {}
    return {
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": _MODERN,
            "io.modelcontextprotocol/clientCapabilities": caps,
        }
    }


def _headers(version: str, *, tool: str | None = None) -> dict[str, str]:
    base = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": version,
    }
    if version == _MODERN:
        base["Mcp-Method"] = "tools/call"
        if tool:
            base["Mcp-Name"] = tool
    return base


async def _handshake(client: httpx.AsyncClient, version: str, *, elicitation: bool) -> str | None:
    """Negotiate a HANDSHAKE-era revision, declaring capabilities as a real client does."""
    caps: dict[str, Any] = {"elicitation": {}} if elicitation else {}
    result = _body(
        await client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": version,
                    "capabilities": caps,
                    "clientInfo": {"name": "claude-code", "version": "2.1.226"},
                },
            },
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        )
    )
    return (result.get("result") or {}).get("protocolVersion")


async def _call_request_approval(
    client: httpx.AsyncClient,
    *,
    version: str,
    seed: dict,
    envelope: dict[str, Any] | None,
    request_state: str | None = None,
    input_responses: dict[str, Any] | None = None,
    msg_id: int = 2,
) -> dict[str, Any]:
    """One ``tools/call`` of ``request_approval``; round 2 adds state + responses."""
    params: dict[str, Any] = {
        "name": "request_approval",
        "arguments": {
            "job_id": seed["job"].job_id,
            "project_id": seed["project"].id,
            "reason": "BE-8003l gate",
            "options": _OPTIONS,
            "context": None,
        },
    }
    if envelope:
        params |= envelope
    if request_state is not None:
        params["requestState"] = request_state
    if input_responses is not None:
        params["inputResponses"] = input_responses
    return _body(
        await client.post(
            "/",
            json={"jsonrpc": "2.0", "id": msg_id, "method": "tools/call", "params": params},
            headers=_headers(version, tool="request_approval"),
        )
    )


def _structured(result: dict[str, Any]) -> dict[str, Any]:
    """The tool's dict payload out of a completed CallToolResult."""
    if result.get("structuredContent"):
        return result["structuredContent"]
    blocks = result.get("content") or []
    assert blocks, f"no content on a completed result: {result!r}"
    return json.loads(blocks[0]["text"])


async def _seed_approval_context(db_session, tenant_key: str, job_type: str = "orchestrator") -> dict:
    """org + product + project + agent_job + agent_execution for one tenant.

    Same shape as ``test_request_approval_mcp_transport._seed_approval_context``;
    ``request_approval`` is orchestrator-only (BE-9054a), hence the default.
    """
    suffix = uuid4().hex[:8]
    db_session.add(Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True))
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"Product {suffix}",
        description="BE-8003l MRTR gate",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"Project {suffix}",
        description="x",
        mission="x",
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type=job_type,
        mission="x",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name=job_type,
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()

    return {"project": project, "job": job, "execution": execution}


@pytest_asyncio.fixture
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def wired_app(db_manager, db_session, tenant_key, monkeypatch):
    """Make the real ASGI transport usable without ``MCPAuthMiddleware``.

    ``wire_client()`` deliberately omits the auth middleware (it pins the PROTOCOL
    surface), so nothing populates the ASGI scope state that ``_resolve_tenant``
    reads -- it would raise "No tenant_key in request state". ``health_check``,
    the only tool that harness calls today, needs no tenant, which is why the gap
    has never mattered before. Patching the same three ``_base`` seams the
    in-memory boundary tests already patch closes it; ``_decide_inline`` imports
    all three from ``_base`` inside its body, so this one patch covers the decide
    leg too.
    """
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.services.user_approval_service import UserApprovalService
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    accessor._user_approval_service = UserApprovalService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)
    # No auth on this chain: without neutralising these the server advertises an
    # empty tool surface and every assertion below would be vacuous. Same seam
    # test_inf9371_wire_revisions uses, for the same reason.
    monkeypatch.setattr(mcp_sdk_server, "_scopes_from_request", lambda _request: None)
    monkeypatch.setattr(mcp_sdk_server, "_profile_toolset_from_request", lambda _request: None)

    try:
        yield
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _approvals_for(db_session, job_id: str) -> list[UserApproval]:
    return list((await db_session.execute(select(UserApproval).where(UserApproval.job_id == job_id))).scalars().all())


class TestCapableClientGetsTheMrtrPath:
    """Modern era + declared elicitation: the two-round flow, end to end."""

    async def test_round_one_asks_and_round_two_decides(self, wired_app, db_session, tenant_key):
        seed = await _seed_approval_context(db_session, tenant_key)

        async with wire_client() as client:
            first = await _call_request_approval(
                client, version=_MODERN, seed=seed, envelope=_envelope(elicitation=True)
            )
            assert first.get("error") is None, f"round 1 errored: {first.get('error')!r}"
            result = first["result"]

            assert result.get("resultType") == "input_required", (
                "a capable client must be OFFERED the inline approval instead of being told to wait; "
                f"got resultType={result.get('resultType')!r}"
            )
            state = result.get("requestState")
            assert isinstance(state, str) and state.startswith("v1."), (
                f"requestState must be sealed by the SDK boundary, got {state!r}"
            )
            requests = result.get("inputRequests") or {}
            assert len(requests) == 1, f"expected exactly one embedded elicitation, got {sorted(requests)}"
            embedded = next(iter(requests.values()))
            assert embedded["method"] == "elicitation/create"
            enum_values = embedded["params"]["requestedSchema"]["properties"]["choice"]["enum"]
            assert set(enum_values) == {"approve", "rework"}, (
                f"the elicitation must offer the caller's own option ids, got {enum_values!r}"
            )

            # The row is parked BEFORE we ask -- the museum's park-and-refuse
            # semantics happen on round 1 whether or not the client ever answers.
            parked = await _approvals_for(db_session, seed["job"].job_id)
            assert len(parked) == 1 and parked[0].status == "pending"

            second = await _call_request_approval(
                client,
                version=_MODERN,
                seed=seed,
                envelope=_envelope(elicitation=True),
                request_state=state,
                input_responses={next(iter(requests)): {"action": "accept", "content": {"choice": "approve"}}},
                msg_id=3,
            )

        assert second.get("error") is None, f"round 2 errored: {second.get('error')!r}"
        payload = _structured(second["result"])
        assert payload["status"] == "decided", f"round 2 must resolve the approval, got {payload!r}"
        assert payload["decided_option_id"] == "approve"

        rows = await _approvals_for(db_session, seed["job"].job_id)
        assert len(rows) == 1, (
            "round 2 re-enters request_approval with byte-identical arguments; a second parked row means the "
            f"request_state check ran below dispatch. Rows: {[(r.id, r.status) for r in rows]}"
        )
        await db_session.refresh(rows[0])
        assert rows[0].status == "decided"
        assert rows[0].decided_option_id == "approve"

    async def test_round_two_declined_leaves_the_approval_for_the_dashboard(self, wired_app, db_session, tenant_key):
        seed = await _seed_approval_context(db_session, tenant_key)

        async with wire_client() as client:
            first = await _call_request_approval(
                client, version=_MODERN, seed=seed, envelope=_envelope(elicitation=True)
            )
            result = first["result"]
            key = next(iter(result["inputRequests"]))
            second = await _call_request_approval(
                client,
                version=_MODERN,
                seed=seed,
                envelope=_envelope(elicitation=True),
                request_state=result["requestState"],
                input_responses={key: {"action": "decline"}},
                msg_id=3,
            )

        assert second.get("error") is None
        payload = _structured(second["result"])
        assert payload["status"] == "pending", "a declined inline choice must leave the dashboard gate intact"
        rows = await _approvals_for(db_session, seed["job"].job_id)
        assert len(rows) == 1
        await db_session.refresh(rows[0])
        assert rows[0].status == "pending"

    async def test_round_two_without_responses_does_not_ask_again(self, wired_app, db_session, tenant_key):
        """Stop-condition: a client that retries carrying state but no answer must converge.

        Re-asking here would let a client that cannot answer loop forever.
        """
        seed = await _seed_approval_context(db_session, tenant_key)

        async with wire_client() as client:
            first = await _call_request_approval(
                client, version=_MODERN, seed=seed, envelope=_envelope(elicitation=True)
            )
            second = await _call_request_approval(
                client,
                version=_MODERN,
                seed=seed,
                envelope=_envelope(elicitation=True),
                request_state=first["result"]["requestState"],
                msg_id=3,
            )

        assert second.get("error") is None
        assert second["result"].get("resultType") != "input_required", "an unanswered retry must not re-ask"
        assert _structured(second["result"])["status"] == "pending"
        assert len(await _approvals_for(db_session, seed["job"].job_id)) == 1


class TestNonCapableClientsAreUnchanged:
    """DoD 2 -- graceful degradation. Both of these are green on master too."""

    async def test_modern_client_without_the_capability_gets_todays_answer(self, wired_app, db_session, tenant_key):
        seed = await _seed_approval_context(db_session, tenant_key)

        async with wire_client() as client:
            result = await _call_request_approval(
                client, version=_MODERN, seed=seed, envelope=_envelope(elicitation=False)
            )

        assert result.get("error") is None, f"{result.get('error')!r}"
        assert result["result"].get("resultType") != "input_required"
        payload = _structured(result["result"])
        assert set(payload) - {"_meta"} == {"approval_id", "status"}
        assert payload["status"] == "pending"

        rows = await _approvals_for(db_session, seed["job"].job_id)
        assert len(rows) == 1 and rows[0].status == "pending"

    async def test_legacy_client_is_unchanged_and_is_not_an_internal_error(self, wired_app, db_session, tenant_key):
        """The gate reads the ERA first, and this is why.

        A 2025-11-25 session declaring elicitation is the live production fleet.
        ``InputRequiredResult`` is not a legal ``tools/call`` result on that
        revision -- the SDK's per-revision serializer rejects it as a -32603
        Internal error, which would have hit EVERY production approval. Red
        against a capability-only gate; that is the version of this feature a
        careful person would otherwise have written.
        """
        seed = await _seed_approval_context(db_session, tenant_key)

        async with wire_client() as client:
            negotiated = await _handshake(client, _LEGACY, elicitation=True)
            assert negotiated == _LEGACY
            result = await _call_request_approval(client, version=_LEGACY, seed=seed, envelope=None)

        assert result.get("error") is None, (
            f"a legacy client must keep today's park-and-refuse answer, not a protocol error: {result.get('error')!r}"
        )
        assert result["result"].get("resultType") != "input_required"
        payload = _structured(result["result"])
        assert payload["status"] == "pending"

        rows = await _approvals_for(db_session, seed["job"].job_id)
        assert len(rows) == 1 and rows[0].status == "pending"

    async def test_a_legacy_revision_declaring_capabilities_is_still_refused_the_offer(
        self, wired_app, db_session, tenant_key
    ):
        """A legacy revision that ALSO presents the modern capability envelope.

        Honest scope, measured rather than assumed: this does NOT discriminate an
        era gate from a capability gate either. I wrote it expecting it to, then
        ran the capability-only mutation and it stayed green -- under our shipped
        ``stateless_http=True`` a legacy-negotiated request never surfaces
        ``client_capabilities`` at all, whichever way the capabilities are
        presented. So at the transport level there is no reachable client shape
        today where the two gates disagree, and the era gate's teeth are in
        ``tests/unit/test_be6038_inline_approval_elicit.py``, whose contexts model
        the session-ful world where they do.

        What this case is worth keeping for: it pins that presenting capabilities
        on a legacy revision produces today's answer and not a protocol error --
        the shape a future session-ful transport would make reachable.
        """
        seed = await _seed_approval_context(db_session, tenant_key)

        async with wire_client() as client:
            result = await _call_request_approval(
                client,
                version=_LEGACY,
                seed=seed,
                envelope={
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": _LEGACY,
                        "io.modelcontextprotocol/clientCapabilities": {"elicitation": {"form": {}}},
                    }
                },
            )

        assert result.get("error") is None, (
            "declaring elicitation must not drag a legacy session onto a result shape its "
            f"revision cannot carry: {result.get('error')!r}"
        )
        assert result["result"].get("resultType") != "input_required"
        assert _structured(result["result"])["status"] == "pending"


class TestTheOrchestratorOnlyRejectionIsUntouched:
    """BE-6081 museum zone: a worker rejection carries no approval to offer."""

    async def test_a_worker_rejection_is_never_turned_into_an_elicitation(self, wired_app, db_session, tenant_key):
        seed = await _seed_approval_context(db_session, tenant_key, job_type="implementer")

        async with wire_client() as client:
            result = await _call_request_approval(
                client, version=_MODERN, seed=seed, envelope=_envelope(elicitation=True)
            )

        assert result.get("error") is None
        assert result["result"].get("resultType") != "input_required"
        payload = _structured(result["result"])
        assert payload["success"] is False
        assert payload["error"] == "ORCHESTRATOR_ONLY_APPROVAL"
        assert await _approvals_for(db_session, seed["job"].job_id) == []
