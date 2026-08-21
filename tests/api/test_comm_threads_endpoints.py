# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""REST endpoint tests for the Agent Message Hub (BE-6054ef).

Tests the full contract of /api/v1/threads:
- CRUD: create, list, history, participants, post, baton, search, my-turn
- Tenant isolation: tenant B cannot read or post to tenant A's threads
- WS broadcast: broadcast_event_to_tenant is called on post and baton
- Input validation: 422 on empty content, 404 on unknown thread
- Username injection: post stamped with user's display_name, not an agent id

Parallel-safe: uses api_client fixture (fresh db_manager session per test),
no module-level mutable state, no test ordering dependencies.
"""

from __future__ import annotations

import secrets
import uuid
from unittest.mock import AsyncMock

import bcrypt
import pytest
from httpx import AsyncClient

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import User
from giljo_mcp.models.comm import CommParticipant
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Seed helper
# ---------------------------------------------------------------------------


async def _seed_tenant(db_manager) -> dict:
    """Create org + user in a fresh isolated tenant. Returns auth headers + ids."""
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()

        org = Organization(
            name=f"Org {suffix}",
            slug=f"org-{suffix}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        pw_hash = bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode()
        user = User(
            username=f"user_{suffix}",
            email=f"user_{suffix}@example.com",
            password_hash=pw_hash,
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
            first_name="Test",
            last_name=f"User{suffix}",
        )
        session.add(user)
        await session.flush()

        # Seed the CHT taxonomy type required by CommThreadRepository.
        with tenant_session_context(session, tenant_key):
            await ensure_default_types_seeded(session, tenant_key)

        await session.commit()

        token = JWTManager.create_access_token(
            user_id=user.id,
            username=user.username,
            role="developer",
            tenant_key=tenant_key,
        )
        headers = {
            "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
            "X-CSRF-Token": _TEST_CSRF_TOKEN,
        }
        return {
            "tenant_key": tenant_key,
            "user_id": user.id,
            "username": user.username,
            "headers": headers,
        }


# ---------------------------------------------------------------------------
# Helper: create a thread via REST
# ---------------------------------------------------------------------------


async def _create_thread(api_client: AsyncClient, headers: dict, subject: str = "Test Thread") -> dict:
    resp = await api_client.post("/api/v1/threads", headers=headers, json={"subject": subject})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Core CRUD tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_thread_returns_chat_id(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)
    body = await _create_thread(api_client, seed["headers"], subject="Hello Hub")
    assert body["chat_id"].startswith("CHT-")
    assert body["status"] == "open"
    assert body["subject"] == "Hello Hub"


@pytest.mark.asyncio
async def test_list_threads_shows_created(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)
    await _create_thread(api_client, seed["headers"], subject="ListMe")
    resp = await api_client.get("/api/v1/threads", headers=seed["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] >= 1
    subjects = [t["subject"] for t in body["threads"]]
    assert "ListMe" in subjects


@pytest.mark.asyncio
async def test_list_threads_carries_the_last_message_anchor(api_client: AsyncClient, db_manager) -> None:
    """FE-9418: the listed card names the POST it summarises, not just the thread.

    Asserted at the HTTP boundary and not only at the repository, because the enrichment
    is OPT-IN on ``viewer_id`` and this endpoint is where that opt-in is made
    (``comm_threads.py`` passes ``current_user.id``). A repository-only test would stay
    green if the anchor never reached a client.

    The anchor is compared against the thread id: an unlabelled projection would collide
    with ``CommThread.id`` in the row tuple and serve the thread id here, which every
    weaker check ("present", "a string", "a UUID") would accept.
    """
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"], subject="AnchorMe")
    thread_id = thread["thread_id"]
    posted = await api_client.post(
        f"/api/v1/threads/{thread_id}/post",
        headers=seed["headers"],
        json={"content": "over to you"},
    )
    assert posted.status_code == 200, posted.text

    resp = await api_client.get("/api/v1/threads", headers=seed["headers"])
    assert resp.status_code == 200, resp.text
    card = next(t for t in resp.json()["threads"] if t["thread_id"] == thread_id)

    assert card["last_message"]["excerpt"] == "over to you"
    assert card["last_message"]["id"] == posted.json()["message_id"]
    assert card["last_message"]["id"] != thread_id


@pytest.mark.asyncio
async def test_post_to_thread_username_injection(api_client: AsyncClient, db_manager) -> None:
    """post_to_thread stamps the user's display_name, not an agent id."""
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]

    resp = await api_client.post(
        f"/api/v1/threads/{thread_id}/post",
        headers=seed["headers"],
        json={"content": "Hello from user"},
    )
    assert resp.status_code == 200, resp.text

    hist = await api_client.get(f"/api/v1/threads/{thread_id}", headers=seed["headers"])
    assert hist.status_code == 200, hist.text
    messages = hist.json()["messages"]
    assert len(messages) >= 1
    last = messages[-1]
    assert last["content"] == "Hello from user"
    # The service stamps the user's display_name, not the agent id string
    assert last["from_display_name"] != seed["user_id"]


@pytest.mark.asyncio
async def test_post_direct_to_participant(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]

    other_participant = "agent_abc"
    join_resp = await api_client.post(
        f"/api/v1/threads/{thread_id}/post",
        headers=seed["headers"],
        json={"content": "Direct msg", "to_participant": other_participant},
    )
    assert join_resp.status_code == 200, join_resp.text
    result = join_resp.json()
    assert result["recipients"] == [other_participant]


@pytest.mark.asyncio
async def test_pass_baton_shows_in_my_turn(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]

    # Pass baton to the user themselves
    baton_resp = await api_client.post(
        f"/api/v1/threads/{thread_id}/baton",
        headers=seed["headers"],
        json={"to": seed["user_id"]},
    )
    assert baton_resp.status_code == 200, baton_resp.text

    my_turn_resp = await api_client.get("/api/v1/threads/my-turn", headers=seed["headers"])
    assert my_turn_resp.status_code == 200, my_turn_resp.text
    body = my_turn_resp.json()
    thread_ids = [t["thread_id"] for t in body["threads"]]
    assert thread_id in thread_ids


@pytest.mark.asyncio
async def test_search_by_subject_keyword(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)
    await _create_thread(api_client, seed["headers"], subject="UniqueSearchKeyword99")

    resp = await api_client.get(
        "/api/v1/threads/search",
        headers=seed["headers"],
        params={"query": "UniqueSearchKeyword99"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] >= 1
    subjects = [t["subject"] for t in body["threads"]]
    assert "UniqueSearchKeyword99" in subjects


@pytest.mark.asyncio
async def test_participants_endpoint_returns_creator(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]

    resp = await api_client.get(f"/api/v1/threads/{thread_id}/participants", headers=seed["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["thread_id"] == thread_id
    assert body["count"] >= 1
    participant_ids = [p["participant_id"] for p in body["participants"]]
    assert seed["user_id"] in participant_ids


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_isolation_get_thread(api_client: AsyncClient, db_manager) -> None:
    """Tenant B gets 404 on tenant A's thread id."""
    a = await _seed_tenant(db_manager)
    b = await _seed_tenant(db_manager)

    thread = await _create_thread(api_client, a["headers"])
    thread_id = thread["thread_id"]

    resp = await api_client.get(f"/api/v1/threads/{thread_id}", headers=b["headers"])
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_tenant_isolation_post_to_thread(api_client: AsyncClient, db_manager) -> None:
    """Tenant B cannot post to tenant A's thread."""
    a = await _seed_tenant(db_manager)
    b = await _seed_tenant(db_manager)

    thread = await _create_thread(api_client, a["headers"])
    thread_id = thread["thread_id"]

    resp = await api_client.post(
        f"/api/v1/threads/{thread_id}/post",
        headers=b["headers"],
        json={"content": "Cross-tenant intrusion"},
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Input validation gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_empty_content_returns_422(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])

    resp = await api_client.post(
        f"/api/v1/threads/{thread['thread_id']}/post",
        headers=seed["headers"],
        json={"content": ""},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_get_missing_thread_returns_404(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)
    fake_id = str(uuid.uuid4())
    resp = await api_client.get(f"/api/v1/threads/{fake_id}", headers=seed["headers"])
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_search_missing_query_returns_422(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)
    resp = await api_client.get("/api/v1/threads/search", headers=seed["headers"])
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# WS broadcast assertions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_broadcast_on_post(api_client: AsyncClient, db_manager) -> None:
    """broadcast_event_to_tenant is called with type=thread_message on post."""
    from api.app_state import state

    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])

    mock_ws = AsyncMock()
    original = state.websocket_manager
    state.websocket_manager = mock_ws
    try:
        resp = await api_client.post(
            f"/api/v1/threads/{thread['thread_id']}/post",
            headers=seed["headers"],
            json={"content": "WS test message"},
        )
        assert resp.status_code == 200, resp.text
    finally:
        state.websocket_manager = original

    mock_ws.broadcast_event_to_tenant.assert_called()
    calls = mock_ws.broadcast_event_to_tenant.call_args_list
    event_types = [call.args[1]["type"] if call.args else call.kwargs["event"]["type"] for call in calls]
    assert "thread_message" in event_types


@pytest.mark.asyncio
async def test_ws_broadcast_on_baton(api_client: AsyncClient, db_manager) -> None:
    """broadcast_event_to_tenant is called with type=thread_update on baton."""
    from api.app_state import state

    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])

    mock_ws = AsyncMock()
    original = state.websocket_manager
    state.websocket_manager = mock_ws
    try:
        resp = await api_client.post(
            f"/api/v1/threads/{thread['thread_id']}/baton",
            headers=seed["headers"],
            json={"to": seed["user_id"]},
        )
        assert resp.status_code == 200, resp.text
    finally:
        state.websocket_manager = original

    mock_ws.broadcast_event_to_tenant.assert_called()
    calls = mock_ws.broadcast_event_to_tenant.call_args_list
    event_types = [call.args[1]["type"] if call.args else call.kwargs["event"]["type"] for call in calls]
    assert "thread_update" in event_types


# ---------------------------------------------------------------------------
# Soft delete (ce_0057)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_thread_removes_from_reads(api_client: AsyncClient, db_manager) -> None:
    """DELETE soft-deletes: the thread drops out of list, history (404), and search."""
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"], subject="DeleteMe42")
    thread_id = thread["thread_id"]

    resp = await api_client.delete(f"/api/v1/threads/{thread_id}", headers=seed["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted"] is True
    assert body["thread_id"] == thread_id

    # No longer listed
    listed = await api_client.get("/api/v1/threads", headers=seed["headers"])
    assert thread_id not in [t["thread_id"] for t in listed.json()["threads"]]

    # History now 404s (read filters deleted_at IS NULL)
    hist = await api_client.get(f"/api/v1/threads/{thread_id}", headers=seed["headers"])
    assert hist.status_code == 404, hist.text

    # Not surfaced by search either
    found = await api_client.get("/api/v1/threads/search", headers=seed["headers"], params={"query": "DeleteMe42"})
    assert thread_id not in [t["thread_id"] for t in found.json()["threads"]]


@pytest.mark.asyncio
async def test_delete_missing_thread_returns_404(api_client: AsyncClient, db_manager) -> None:
    seed = await _seed_tenant(db_manager)
    fake_id = str(uuid.uuid4())
    resp = await api_client.delete(f"/api/v1/threads/{fake_id}", headers=seed["headers"])
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_delete_twice_returns_404(api_client: AsyncClient, db_manager) -> None:
    """A second delete on the same thread 404s — it is already soft-deleted."""
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]

    first = await api_client.delete(f"/api/v1/threads/{thread_id}", headers=seed["headers"])
    assert first.status_code == 200, first.text
    second = await api_client.delete(f"/api/v1/threads/{thread_id}", headers=seed["headers"])
    assert second.status_code == 404, second.text


@pytest.mark.asyncio
async def test_tenant_isolation_delete_thread(api_client: AsyncClient, db_manager) -> None:
    """Tenant B cannot delete tenant A's thread (404), and A's thread survives."""
    a = await _seed_tenant(db_manager)
    b = await _seed_tenant(db_manager)

    thread = await _create_thread(api_client, a["headers"])
    thread_id = thread["thread_id"]

    resp = await api_client.delete(f"/api/v1/threads/{thread_id}", headers=b["headers"])
    assert resp.status_code == 404, resp.text

    # A's thread is untouched
    still = await api_client.get(f"/api/v1/threads/{thread_id}", headers=a["headers"])
    assert still.status_code == 200, still.text


@pytest.mark.asyncio
async def test_ws_broadcast_on_delete(api_client: AsyncClient, db_manager) -> None:
    """broadcast_event_to_tenant fires thread_update(update_type=deleted) on delete."""
    from api.app_state import state

    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])

    mock_ws = AsyncMock()
    original = state.websocket_manager
    state.websocket_manager = mock_ws
    try:
        resp = await api_client.delete(f"/api/v1/threads/{thread['thread_id']}", headers=seed["headers"])
        assert resp.status_code == 200, resp.text
    finally:
        state.websocket_manager = original

    mock_ws.broadcast_event_to_tenant.assert_called()
    calls = mock_ws.broadcast_event_to_tenant.call_args_list
    events = [call.args[1] if call.args else call.kwargs["event"] for call in calls]
    deleted = [e for e in events if e["type"] == "thread_update" and e["data"].get("update_type") == "deleted"]
    assert deleted, "expected a thread_update(deleted) broadcast"


# ---------------------------------------------------------------------------
# BE-9142: bounded GET /{thread_id} history via the existing service params
# (after_message_id / since / tail — BE-6226). The bound is OPT-IN: with none
# of the three the read is the full timeline, unchanged for existing consumers.
# ---------------------------------------------------------------------------


async def _post_messages(api_client: AsyncClient, headers: dict, thread_id: str, contents: list[str]) -> None:
    """Post each content string to the thread in order (distinct created_at per post)."""
    for content in contents:
        resp = await api_client.post(
            f"/api/v1/threads/{thread_id}/post",
            headers=headers,
            json={"content": content},
        )
        assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_history_no_params_returns_full_timeline(api_client: AsyncClient, db_manager) -> None:
    """Characterization: with NO bounding params the REST read is the full timeline.

    Guards the DoD invariant that BE-9142 does not change the existing (frontend)
    caller's result — the bound is opt-in.
    """
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]
    await _post_messages(api_client, seed["headers"], thread_id, [f"m{i}" for i in range(6)])

    resp = await api_client.get(f"/api/v1/threads/{thread_id}", headers=seed["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    contents = [m["content"] for m in body["messages"]]
    assert contents == [f"m{i}" for i in range(6)]  # all present, oldest-first
    assert body["count"] == 6


@pytest.mark.asyncio
async def test_history_tail_returns_last_n(api_client: AsyncClient, db_manager) -> None:
    """?tail=N returns only the last N messages, oldest-first."""
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]
    await _post_messages(api_client, seed["headers"], thread_id, [f"m{i}" for i in range(6)])

    resp = await api_client.get(f"/api/v1/threads/{thread_id}", headers=seed["headers"], params={"tail": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 2
    assert [m["content"] for m in body["messages"]] == ["m4", "m5"]


@pytest.mark.asyncio
async def test_history_after_message_id_returns_only_newer(api_client: AsyncClient, db_manager) -> None:
    """?after_message_id=<id> returns only messages created after that message."""
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]
    await _post_messages(api_client, seed["headers"], thread_id, [f"m{i}" for i in range(4)])

    full = (await api_client.get(f"/api/v1/threads/{thread_id}", headers=seed["headers"])).json()["messages"]
    cursor_id = full[1]["message_id"]  # after m1

    resp = await api_client.get(
        f"/api/v1/threads/{thread_id}", headers=seed["headers"], params={"after_message_id": cursor_id}
    )
    assert resp.status_code == 200, resp.text
    assert [m["content"] for m in resp.json()["messages"]] == ["m2", "m3"]


@pytest.mark.asyncio
async def test_history_since_filters_by_timestamp(api_client: AsyncClient, db_manager) -> None:
    """?since=<iso ts> returns only messages created strictly after it."""
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]
    await _post_messages(api_client, seed["headers"], thread_id, [f"m{i}" for i in range(4)])

    full = (await api_client.get(f"/api/v1/threads/{thread_id}", headers=seed["headers"])).json()["messages"]
    since_ts = full[1]["created_at"]  # strictly after m1 -> m2, m3

    resp = await api_client.get(f"/api/v1/threads/{thread_id}", headers=seed["headers"], params={"since": since_ts})
    assert resp.status_code == 200, resp.text
    assert [m["content"] for m in resp.json()["messages"]] == ["m2", "m3"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_tail", [0, 501])
async def test_history_tail_out_of_bounds_returns_422(api_client: AsyncClient, db_manager, bad_tail: int) -> None:
    """?tail outside 1..500 is rejected at the API layer (422), never a 500."""
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    resp = await api_client.get(
        f"/api/v1/threads/{thread['thread_id']}", headers=seed["headers"], params={"tail": bad_tail}
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_history_after_and_since_mutually_exclusive_returns_400(api_client: AsyncClient, db_manager) -> None:
    """after_message_id + since together is a clean 400 (both name a start marker)."""
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]
    await _post_messages(api_client, seed["headers"], thread_id, ["m0"])

    resp = await api_client.get(
        f"/api/v1/threads/{thread_id}",
        headers=seed["headers"],
        params={"after_message_id": "anything", "since": "2026-01-01T00:00:00+00:00"},
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_post_to_a_display_label_is_refused_cleanly_not_a_500(api_client: AsyncClient, db_manager) -> None:
    """BE-9292a-F1 second-order guard at the REST layer.

    This route forwards no baton, so before the ADDRESSEE was screened the service
    could never refuse it and every ``result["message_id"]`` access below was safe. A
    directed post naming a display label is declined now, and a rejection carries no
    ``message_id`` — so without the early return the clean refusal became a KeyError
    500 on the reactivation hop and the WS fan-out.
    """
    seed = await _seed_tenant(db_manager)
    thread = await _create_thread(api_client, seed["headers"])
    thread_id = thread["thread_id"]

    # No REST route enrols a participant (join_thread is MCP-side), so the conductor's
    # id-with-a-display-name row is seeded directly.
    async with db_manager.get_session_async() as session:
        session.add(
            CommParticipant(
                tenant_key=seed["tenant_key"],
                thread_id=thread_id,
                participant_id="36eac157-uuid",
                participant_type="agent",
                display_name="Ledger Zero Conductor",
            )
        )
        await session.commit()

    # The websocket manager MUST be live for this test to mean anything. The
    # reactivation hop's own result["message_id"] read sits inside a best-effort
    # try/except that swallows the KeyError, so the only place the missing key
    # actually reaches the client is the WS fan-out — with no manager installed this
    # test passes whether or not the guard exists.
    from api.app_state import state

    mock_ws = AsyncMock()
    original = state.websocket_manager
    state.websocket_manager = mock_ws
    try:
        resp = await api_client.post(
            f"/api/v1/threads/{thread_id}/post",
            headers=seed["headers"],
            json={"content": "decision needed", "to_participant": "Ledger Zero Conductor", "requires_action": True},
        )
    finally:
        state.websocket_manager = original

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is False
    assert body["error"] == "TARGET_IS_A_DISPLAY_NAME"
    assert body["registered_id"] == "36eac157-uuid"
    # A refusal is not a post: nothing was persisted, so nothing may be announced.
    mock_ws.broadcast_event_to_tenant.assert_not_called()
