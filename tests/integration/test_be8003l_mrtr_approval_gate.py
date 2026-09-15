# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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

from tests.integration.test_inf9371_wire_revisions import _body, wire_client


pytestmark = pytest.mark.asyncio

_MODERN = "2026-07-28"
_LEGACY = "2025-11-25"

_OPTIONS = [{"id": "approve", "label": "Approve"}, {"id": "rework", "label": "Rework"}]


def _envelope(*, elicitation: bool) -> dict[str, Any]:
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
    if result.get("structuredContent"):
        return result["structuredContent"]
    blocks = result.get("content") or []
    assert blocks, f"no content on a completed result: {result!r}"
    return json.loads(blocks[0]["text"])


async def _seed_approval_context(db_session, tenant_key: str, job_type: str = "orchestrator") -> dict:
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
    monkeypatch.setattr(mcp_sdk_server, "_scopes_from_request", lambda _request: None)
    monkeypatch.setattr(mcp_sdk_server, "_profile_toolset_from_request", lambda _request: None)

    try:
        yield
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _approvals_for(db_session, job_id: str) -> list[UserApproval]:
    return list((await db_session.execute(select(UserApproval).where(UserApproval.job_id == job_id))).scalars().all())


class TestCapableClientGetsTheMrtrPath:

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
