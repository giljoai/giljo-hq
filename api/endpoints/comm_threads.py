# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""REST adapter for the Agent Message Hub (BE-6054ef).

Thin shim over CommThreadService — no business logic here. Registration:
  prefix="/api/v1/threads", tags=["comm-threads"]

WS broadcasts are best-effort (post + baton mutations only). A WS failure
NEVER turns a successful DB write into a 500 — see _comm_ws helpers.
"""

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

# Max content length accepted from the UI (mirrors MCP_MESSAGE_MAX on the tool path).
_CONTENT_MAX = 20_000
_SUBJECT_MAX = 255
_ID_MAX = 64


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateThreadRequest(BaseModel):
    subject: str | None = Field(None, max_length=_SUBJECT_MAX)
    severity: str | None = Field(None, max_length=20)
    product_id: str | None = Field(None, max_length=_ID_MAX)
    project_id: str | None = Field(None, max_length=_ID_MAX)


class UpdateThreadRequest(BaseModel):
    """BE-9289b: operator edit of a thread. Both fields optional — send either or both.

    ``status`` is constrained to the settable lifecycle here as well as in the service,
    so a bad value is a 422 at the boundary rather than reaching the owning service.
    """

    subject: str | None = Field(None, max_length=_SUBJECT_MAX)
    status: Literal["open", "active", "resolved", "closed"] | None = Field(None)


class PostToThreadRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=_CONTENT_MAX)
    to_participant: str | None = Field(None, max_length=_ID_MAX)
    set_status: Literal["open", "active", "resolved", "closed"] | None = None
    requires_action: bool = False
    loop_directive: bool = False
    # FE-6140: auto-check-in cadence (minutes) carried on a loop_directive post.
    # Round-trips FE -> backend -> persisted; surfaced on the poll responses. Bounds
    # mirror the service (1..1440); the FE slider stays within 5..60.
    loop_interval_minutes: int | None = Field(None, ge=1, le=1440)
    priority: str = Field("normal", max_length=20)


class PassBatonRequest(BaseModel):
    to: str = Field(..., min_length=1, max_length=_ID_MAX)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


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
        # BE-9289b: the dashboard is a card surface, so it gets the enriched payload —
        # project_name, participants, last_message and a per-viewer unread flag — in one
        # extra round trip instead of the follow-up call per thread it used to make.
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
    """Append a message to a thread. Broadcasts thread_message + thread_update (on status change)."""
    result = await service.post_to_thread(
        thread_id=thread_id,
        content=body.content,
        to_participant=body.to_participant,
        set_status=body.set_status,
        requires_action=body.requires_action,
        loop_directive=body.loop_directive,
        loop_interval_minutes=body.loop_interval_minutes,
        priority=body.priority,
        user_id=current_user.id,
        tenant_key=current_user.tenant_key,
    )
    # BE-9292a-F1: this route forwards no baton, so before the addressee was screened
    # it could never be refused and every access below was safe. It can be now — a
    # directed post naming a display label is declined — and a rejection carries no
    # message_id, so returning early is what keeps `result["message_id"]` honest
    # instead of turning a clean refusal into a 500.
    if result.get("success") is False:
        return result
    # BE-9012b (D5): a human posting a DIRECTED, action-required post to a
    # project-bound thread SHOULD wake the completed agent (that's the feature) —
    # the same relocated auto-block the MCP wrapper runs. Town-square / informational
    # / broadcast posts are inert (guarded inside auto_block_for_thread_post). Best-
    # effort: never unwind the already-committed post if reactivation hiccups.
    if body.requires_action and body.to_participant:
        try:
            outcome = await routing_service.auto_block_for_thread_post(
                message_id=result["message_id"],
                to_participant=body.to_participant,
                sender_display_name=result.get("from_display_name", current_user.display_name),
                requires_action=body.requires_action,
                tenant_key=current_user.tenant_key,
            )
            # BE-9247: surface the forward-on-send outcome in the SAME response so the
            # sender learns immediately (e.g. "Tester was closed -- your message was
            # forwarded to the orchestrator"), rather than discarding it silently.
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
            from_kind=result.get("from_kind", "user"),  # BE-9289a (REST post = the operator)
            content=body.content,
            message_type="direct" if body.to_participant else "broadcast",
            priority=body.priority,
            requires_action=body.requires_action,
            project_id=None,
        )
        if body.set_status:
            history = await service.get_thread_history(thread_id=thread_id, tenant_key=current_user.tenant_key)
            t = history["thread"]
            await broadcast_thread_update(
                state.websocket_manager,
                current_user.tenant_key,
                thread_id=thread_id,
                chat_id=t["chat_id"],
                status=t["status"],
                next_action_owner=t.get("next_action_owner"),
                update_type="status",
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
        tenant_key=current_user.tenant_key,
    )
    # BE-9292a: an undeliverable target is refused and the owner is unchanged —
    # broadcasting here would tell the Hub the baton had moved when it had not.
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
        )
    return result
