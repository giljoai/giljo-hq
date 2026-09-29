# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.endpoints._comm_ws import broadcast_thread_message, broadcast_thread_update
from api.endpoints.dependencies import (
    get_comm_thread_service,
    get_message_routing_service,
)
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.message_routing_service import MessageRoutingService
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)
router = APIRouter()

_CONTENT_MAX = 20_000
_SUBJECT_MAX = 255
_ID_MAX = 64




class CreateThreadRequest(BaseModel):
    subject: str | None = Field(None, max_length=_SUBJECT_MAX)
    severity: str | None = Field(None, max_length=20)
    product_id: str | None = Field(None, max_length=_ID_MAX)
    project_id: str | None = Field(None, max_length=_ID_MAX)


class UpdateThreadRequest(BaseModel):
    """BE-9289b/FE-9530: operator edit of a thread. All fields optional — send any subset.

    ``status`` is constrained to the settable lifecycle here as well as in the service,
    so a bad value is a 422 at the boundary rather than reaching the owning service.

    FE-9530: ``product_id``/``clear_product`` retag the thread's product.
    Retagging is the only way an existing thread that predates mandatory
    tagging gets one -- there is no bulk migration.
    ``project_ids`` is the plural project-tag set: omit to leave tags
    alone, ``[]`` to clear them, a list to full-replace them.
    """

    subject: str | None = Field(None, max_length=_SUBJECT_MAX)
    status: Literal["open", "active", "resolved", "closed"] | None = Field(None)
    product_id: str | None = Field(None, max_length=_ID_MAX)
    clear_product: bool = False
    project_ids: list[str] | None = Field(None, max_length=50)


class PostToThreadRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=_CONTENT_MAX)
    to_participant: str | None = Field(None, max_length=_ID_MAX)
    set_status: Literal["open", "active", "resolved", "closed"] | None = None
    requires_action: bool = False
    loop_directive: bool = False
    loop_interval_minutes: int | None = Field(None, ge=1, le=1440)
    priority: str = Field("normal", max_length=20)


class PassBatonRequest(BaseModel):
    to: str = Field(..., min_length=1, max_length=_ID_MAX)




@router.get("")
async def list_threads(
    status: str | None = Query(None),
    owner: str | None = Query(None),
    product_id: str | None = Query(None),
    project_id: str | None = Query(None),
    limit: int | None = Query(
        50,
        ge=1,
        le=500,
        description="Max threads to return (newest first). BE-6131b: mirrors the BE-6071 bound on /messages.",
    ),
    before_id: str | None = Query(
        None,
        description="Keyset cursor: return threads older than this thread_id (for next page).",
    ),
    current_user: User = Depends(get_current_active_user),
    service: CommThreadService = Depends(get_comm_thread_service),
) -> dict[str, Any]:
    """List threads with optional filters. Returns {count, threads}.

    ``limit`` + ``before_id`` give server-side keyset pagination (default 50, max 500).
    """
    return await service.list_threads(
        status=status,
        owner=owner,
        product_id=product_id,
        project_id=project_id,
        limit=limit,
        before_id=before_id,
        viewer_id=current_user.id,
        tenant_key=current_user.tenant_key,
    )


@router.get("/my-turn")
async def get_my_turn(
    current_user: User = Depends(get_current_active_user),
    service: CommThreadService = Depends(get_comm_thread_service),
) -> dict[str, Any]:
    """Threads where the current user holds the baton (next_action_owner == user id or 'all')."""
    return await service.get_my_turn(
        agent_id=current_user.id,
        tenant_key=current_user.tenant_key,
    )


@router.get("/attention")
async def get_attention(
    current_user: User = Depends(get_current_active_user),
    service: CommThreadService = Depends(get_comm_thread_service),
) -> dict[str, Any]:
    """What is asking for the operator right now (FE-9586).

    Returns ``{mentions, directed_action}``, each a list of ``{thread_id, chat_id}``.

    ONE read on purpose: the banner family it feeds needs ONE loaded state. Split
    across two calls, the family gets two hydration moments and "not fetched yet"
    becomes indistinguishable from "nothing waiting" for whichever half is late --
    which is how a reconcile closes every popout on mount.

    Declared ABOVE ``GET /{thread_id}``: a literal path registered after the
    parameterised one is shadowed by it, and this would resolve as a thread whose id
    is the word "attention". Same reason /my-turn, /search and /deleted sit here.

    Separate from ``/my-turn`` rather than folded into it. That read is
    agent-shaped -- an agent_id, its baton threads, its loop directives -- and is
    part of the MCP tool contract. Mentions for agents are a different question
    nobody has asked; widening the agent surface to serve the dashboard would answer
    it by accident.
    """
    return await service.get_attention_for_user(
        user_id=current_user.id,
        tenant_key=current_user.tenant_key,
    )


@router.get("/search")
async def search_threads(
    query: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
    service: CommThreadService = Depends(get_comm_thread_service),
) -> dict[str, Any]:
    """Full-text search across CHT serial, subject, participants, and message content."""
    return await service.search_threads(
        query=query,
        limit=limit,
        tenant_key=current_user.tenant_key,
    )


@router.get("/chain-hub")
async def get_chain_hub(
    sequence_run_id: str = Query(..., min_length=1, max_length=_ID_MAX),
    current_user: User = Depends(get_current_active_user),
    service: CommThreadService = Depends(get_comm_thread_service),
) -> dict[str, Any]:
    """The coordination hub thread of a chain run, or ``{"thread": null}`` if it has none yet."""
    thread = await service.resolve_chain_hub_thread(
        sequence_run_id=sequence_run_id,
        tenant_key=current_user.tenant_key,
    )
    return {"thread": thread}


@router.get("/deleted")
async def list_deleted_threads(
    product_id: str | None = Query(None),
    project_id: str | None = Query(None),
    current_user: User = Depends(get_current_active_user),
    service: CommThreadService = Depends(get_comm_thread_service),
) -> dict[str, Any]:
    """List soft-deleted threads for the recover dialog. Returns {count, threads}.

    Registered BEFORE ``GET /{thread_id}`` so the literal ``/deleted`` path is not
    swallowed by the thread-id path param.
    """
    return await service.list_deleted_threads(
        product_id=product_id,
        project_id=project_id,
        tenant_key=current_user.tenant_key,
    )


@router.get("/{thread_id}")
async def get_thread_history(
    thread_id: str,
    include_recipient_state: bool = Query(
        default=False,
        description="FE-9012c (D3): also surface per-message recipient acted-on state "
        "(recipients/acked_by/completed_by/pending_for) from the D4 junctions, for the "
        "Hub's in-thread waiting/read/sent filter. Off by default (byte-identical read).",
    ),
    after_message_id: str | None = Query(
        None,
        max_length=_ID_MAX,
        description="BE-9142: incremental cursor — return only messages AFTER this message id. "
        "Mutually exclusive with 'since'. Opt-in; omit for the full timeline.",
    ),
    since: str | None = Query(
        None,
        description="BE-9142: ISO-8601 timestamp — return only messages created strictly after it. "
        "Mutually exclusive with 'after_message_id'. Opt-in; omit for the full timeline.",
    ),
    tail: int | None = Query(
        None,
        ge=1,
        le=500,
        description="BE-9142: return only the last N messages (1..500), applied after any cursor. "
        "Opt-in; omit for the full timeline (byte-identical to the pre-BE-9142 read).",
    ),
    current_user: User = Depends(get_current_active_user),
    service: CommThreadService = Depends(get_comm_thread_service),
) -> dict[str, Any]:
    """Message timeline for a thread. Returns {thread, count, messages}.

    BE-9142: with none of ``after_message_id`` / ``since`` / ``tail`` the read is the
    full timeline (unchanged). Those three bound the read via the existing
    ``CommThreadService.get_thread_history`` params (BE-6226) — no new mechanism, and
    the bound stays opt-in so existing REST consumers (the Hub UI) are unaffected.
    """
    return await service.get_thread_history(
        thread_id=thread_id,
        after_message_id=after_message_id,
        since=since,
        tail=tail,
        include_recipient_state=include_recipient_state,
        tenant_key=current_user.tenant_key,
    )


@router.get("/{thread_id}/participants")
async def get_participants(
    thread_id: str,
    current_user: User = Depends(get_current_active_user),
    service: CommThreadService = Depends(get_comm_thread_service),
) -> dict[str, Any]:
    """Participant directory for a thread. Returns {thread_id, count, participants}."""
    return await service.list_participants(
        thread_id=thread_id,
        tenant_key=current_user.tenant_key,
    )


@router.post("")
async def create_thread(
    body: CreateThreadRequest,
    current_user: User = Depends(get_current_active_user),
    service: CommThreadService = Depends(get_comm_thread_service),
) -> dict[str, Any]:
    """Create a new thread. Returns the thread dict including chat_id (CHT-####)."""
    result = await service.create_thread(
        subject=body.subject,
        severity=body.severity,
        product_id=body.product_id,
        project_id=body.project_id,
        creator_id=current_user.id,
        creator_type="user",
        creator_display_name=current_user.display_name,
        tenant_key=current_user.tenant_key,
    )
    from api.app_state import state

    if state.websocket_manager:
        await broadcast_thread_update(
            state.websocket_manager,
            current_user.tenant_key,
            thread_id=result["thread_id"],
            chat_id=result["chat_id"],
            status=result["status"],
            next_action_owner=result.get("next_action_owner"),
            update_type="created",
        )
    return result


@router.post("/{thread_id}/post")
async def post_to_thread(
    thread_id: str,
    body: PostToThreadRequest,
    current_user: User = Depends(get_current_active_user),
    service: CommThreadService = Depends(get_comm_thread_service),
    routing_service: MessageRoutingService = Depends(get_message_routing_service),
) -> dict[str, Any]:
    """Append a message to a thread. Broadcasts thread_message + thread_update (on status change).

    BE-9560: mirrors what the MCP boundary already does for a post, per operator ruling
    2026-09-02 -- answering a thread should mean answering. A directed reply
    (``to_participant`` set) hands the baton to that addressee, screened the same way
    an MCP auto-pass is; a broadcast reply clears the poster's own held baton (or the
    shared 'all') instead of leaving it to a manual raised-hand control. See
    ``CommThreadService.post_to_thread`` for the exact contract and the guard against
    clearing a baton some other agent still holds.
    """
    result = await service.post_to_thread(
        thread_id=thread_id,
        content=body.content,
        to_participant=body.to_participant,
        pass_baton_to=body.to_participant or None,
        clear_baton_on_broadcast_reply=True,
        set_status=body.set_status,
        requires_action=body.requires_action,
        loop_directive=body.loop_directive,
        loop_interval_minutes=body.loop_interval_minutes,
        priority=body.priority,
        user_id=current_user.id,
        as_user=True,
        tenant_key=current_user.tenant_key,
    )
    if result.get("success") is False:
        return result
    if body.requires_action and body.to_participant:
        try:
            outcome = await routing_service.auto_block_for_thread_post(
                message_id=result["message_id"],
                to_participant=body.to_participant,
                sender_display_name=result.get("from_display_name", current_user.display_name),
                requires_action=body.requires_action,
                tenant_key=current_user.tenant_key,
            )
            if outcome.notice:
                result["forward_notice"] = outcome.notice
        except Exception:  # noqa: BLE001 - reactivation is a follow-on side-effect; post stays authoritative
            logger.warning(
                "REST post_to_thread reactivation auto-block (D5) failed for message %s -> %s (non-fatal)",
                result.get("message_id", ""),
                sanitize(body.to_participant),
                exc_info=True,
            )
    from api.app_state import state

    if state.websocket_manager:
        await broadcast_thread_message(
            state.websocket_manager,
            current_user.tenant_key,
            thread_id=thread_id,
            message_id=result["message_id"],
            from_agent_id=current_user.id,
            from_display_name=result.get("from_display_name", current_user.display_name),
            from_kind=result.get("from_kind", "user"),
            content=body.content,
            message_type="direct" if body.to_participant else "broadcast",
            priority=body.priority,
            requires_action=body.requires_action,
            project_id=None,
            to_participant=result.get("to_participant"),
        )
        baton_changed = bool(result.get("baton_passed") or result.get("baton_cleared"))
        if body.set_status or baton_changed:
            history = await service.get_thread_history(thread_id=thread_id, tenant_key=current_user.tenant_key)
            t = history["thread"]
            if body.set_status:
                await broadcast_thread_update(
                    state.websocket_manager,
                    current_user.tenant_key,
                    thread_id=thread_id,
                    chat_id=t["chat_id"],
                    status=t["status"],
                    next_action_owner=t.get("next_action_owner"),
                    update_type="status",
                )
            if baton_changed:
                await broadcast_thread_update(
                    state.websocket_manager,
                    current_user.tenant_key,
                    thread_id=thread_id,
                    chat_id=t["chat_id"],
                    status=t["status"],
                    next_action_owner=t.get("next_action_owner"),
                    update_type="baton",
                )
    return result


@router.patch("/{thread_id}")
async def update_thread(
    thread_id: str,
    body: UpdateThreadRequest,
    current_user: User = Depends(get_current_active_user),
    service: CommThreadService = Depends(get_comm_thread_service),
) -> dict[str, Any]:
    """Rename a thread and/or set its status (BE-9289b). Broadcasts thread_update.

    Two things the operator could not do before: a thread could only be named at CREATE
    time, and status moved only as a side effect of an agent posting — which is why the
    thread list is a wall of stale "Open".

    A rename is REFUSED on a project-bound thread (clean 400 with the reason, never a
    500): that thread is named after its project and is kept with the project's 360
    memory. Status has no such restriction — resolving or closing a project thread is a
    normal operator action and says nothing about the project's identity.
    """
    result = await service.update_thread(
        thread_id=thread_id,
        subject=body.subject,
        status=body.status,
        product_id=body.product_id,
        clear_product=body.clear_product,
        project_ids=body.project_ids,
        tenant_key=current_user.tenant_key,
    )
    from api.app_state import state

    if state.websocket_manager:
        await broadcast_thread_update(
            state.websocket_manager,
            current_user.tenant_key,
            thread_id=thread_id,
            chat_id=result["chat_id"],
            status=result["status"],
            next_action_owner=result["next_action_owner"],
            subject=result["subject"],
            update_type="updated",
        )
    return result


@router.delete("/{thread_id}")
async def delete_thread(
    thread_id: str,
    current_user: User = Depends(get_current_active_user),
    service: CommThreadService = Depends(get_comm_thread_service),
) -> dict[str, Any]:
    """Soft-delete a thread (Message Hub trash action). Broadcasts thread_update(deleted)."""
    result = await service.delete_thread(
        thread_id=thread_id,
        tenant_key=current_user.tenant_key,
    )
    from api.app_state import state

    if state.websocket_manager:
        await broadcast_thread_update(
            state.websocket_manager,
            current_user.tenant_key,
            thread_id=thread_id,
            chat_id=result["chat_id"],
            status="closed",
            next_action_owner=None,
            update_type="deleted",
        )
    return result


@router.post("/{thread_id}/restore")
async def restore_thread(
    thread_id: str,
    current_user: User = Depends(get_current_active_user),
    service: CommThreadService = Depends(get_comm_thread_service),
) -> dict[str, Any]:
    """Restore a soft-deleted thread (Message Hub recover action).

    Broadcasts thread_update(restored) so other browsers re-surface the thread."""
    result = await service.restore_thread(
        thread_id=thread_id,
        tenant_key=current_user.tenant_key,
    )
    from api.app_state import state

    if state.websocket_manager:
        await broadcast_thread_update(
            state.websocket_manager,
            current_user.tenant_key,
            thread_id=thread_id,
            chat_id=result["chat_id"],
            status=result["status"],
            next_action_owner=result.get("next_action_owner"),
            update_type="restored",
        )
    return result


@router.post("/{thread_id}/baton")
async def pass_baton(
    thread_id: str,
    body: PassBatonRequest,
    current_user: User = Depends(get_current_active_user),
    service: CommThreadService = Depends(get_comm_thread_service),
) -> dict[str, Any]:
    """Pass the baton: set next_action_owner on a thread. Broadcasts thread_update."""
    result = await service.pass_baton(
        thread_id=thread_id,
        to=body.to,
        from_agent=current_user.id,
        tenant_key=current_user.tenant_key,
    )
    if result.get("success") is False:
        return result
    from api.app_state import state

    if state.websocket_manager:
        history = await service.get_thread_history(thread_id=thread_id, tenant_key=current_user.tenant_key)
        t = history["thread"]
        await broadcast_thread_update(
            state.websocket_manager,
            current_user.tenant_key,
            thread_id=thread_id,
            chat_id=t["chat_id"],
            status=t["status"],
            next_action_owner=result.get("next_action_owner"),
            update_type="baton",
            from_display_name=result.get("from_display_name") or current_user.display_name,
            from_kind=result.get("from_kind") or "user",
        )
    return result


@router.post("/{thread_id}/read")
async def mark_thread_read(
    thread_id: str,
    current_user: User = Depends(get_current_active_user),
    service: CommThreadService = Depends(get_comm_thread_service),
) -> dict[str, Any]:
    """Record that the OPERATOR has read this thread (FE-9586).

    The dashboard had no way to say this. ``GET /{thread_id}`` is a pure read and
    the store's ``markThreadRead()`` only zeroed an in-memory counter, so
    ``comm_participants.last_read_at`` -- the cursor the card's ``unread`` flag and
    every "anything new" answer key on -- was advanced only by agents over MCP. The
    operator's card therefore read unread FOREVER once anything had been posted.

    Deliberately a POST with no body: the identity is the session's, never declared,
    and the target is the whole thread up to its newest post. The client fires it
    fire-and-forget on a genuine thread OPEN -- a failed watermark write must never
    delay or break the thread view, and the next open retries it.

    No WebSocket broadcast: this changes what ONE viewer has seen, not the thread.
    Broadcasting it would tell every other client the thread had changed when
    nothing about it had.
    """
    return await service.mark_thread_read_for_user(
        thread_id=thread_id,
        user_id=current_user.id,
        display_name=current_user.display_name,
        tenant_key=current_user.tenant_key,
    )
