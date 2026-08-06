# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Agent Message Hub thread tools — @mcp.tool wrappers (BE-6054b).

The persistent, tenant-isolated message board (BBS). The reply-protocol is
encoded into the tool semantics + descriptions so every vendor's agent complies
without a pasted prose blob: posts are append-only; ``next_action_owner`` is the
baton (``get_my_turn`` finds threads awaiting you); set a terminal status
(resolved/closed) to end a looped conversation.

Each wrapper validates input at the boundary (length caps -> clean 422) and
delegates via ``_call_tool``. ``post_to_thread`` injects the authenticated user's
identity from ``_base._resolve_user_id(ctx)`` so user posts are attributed to the
person, not an agent.
"""

import logging
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from api.endpoints._comm_ws import broadcast_thread_message, broadcast_thread_update
from api.endpoints.mcp_tools import _base
from api.endpoints.mcp_tools._base import (
    MCP_HEAVY_TOOL_META,
    MCP_ID_MAX,
    MCP_MESSAGE_MAX,
    MCP_NAME_MAX,
    MCP_SHORT_TEXT_MAX,
    _call_tool,
    _detected_harness,
    mcp,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints
from giljo_mcp import branding


logger = logging.getLogger(__name__)

# BE-9061: a plain get_thread_history poll (no cursor/marker) reads the WHOLE
# thread timeline, and loop_directive polling makes that the hottest Hub read —
# so a long-lived chain thread gets slower without bound. Default the plain poll
# to the most recent N messages. Callers that truly need the full timeline pass
# tail=0; incremental (after_message_id/since) and unread_only cursor reads are
# already deltas and are NOT capped by this default.
DEFAULT_HISTORY_TAIL = 200


def _resolve_pass_baton_to(pass_baton_to: str, requires_action: bool, to_participant: str) -> str:
    """Resolve post_to_thread's atomic baton hand-off (BE-9197) — THE contract
    agents rely on, resolved at the tool boundary so the REST and internal
    service callers keep prior behavior unless they opt in:

    - an explicit ``pass_baton_to`` always wins;
    - ``'none'`` posts WITHOUT moving the baton (suppresses the default);
    - when absent, a directed action-request (``requires_action=true`` +
      ``to_participant``) auto-passes the baton to that participant — the
      "posted the question, forgot the pass_baton" incident class;
    - every other post (broadcasts included) leaves the baton untouched.

    Returns the owner to hand the baton to, or "" for no baton write.
    """
    resolved = pass_baton_to
    if not resolved and requires_action and to_participant:
        resolved = to_participant
    return "" if resolved == "none" else resolved


@mcp.tool(
    title="Create Thread",
    description=(
        "Create a persistent message-board thread (chat) and get back its CHT-#### "
        "chat id to share so other agents can join_thread. Threads are standalone by "
        "default; pass project_id to anchor one to a project. The creator is registered "
        "as the first participant and holds the baton (next_action_owner). "
        f"{branding.TWO_HUB_DISAMBIGUATION}"
    ),
    annotations=_tool_hints("create_thread"),
)
async def create_thread(
    subject: Annotated[str, Field(max_length=MCP_NAME_MAX, description="Short thread subject / topic.")] = "",
    severity: Annotated[
        str, Field(max_length=MCP_ID_MAX, description="Optional severity label (info|warn|critical|...).")
    ] = "",
    product_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Optional product UUID filter dim.")] = "",
    project_id: Annotated[
        str,
        Field(max_length=MCP_ID_MAX, description="Optional project UUID to anchor the thread. Omit for standalone."),
    ] = "",
    creator_id: Annotated[
        str, Field(max_length=MCP_ID_MAX, description="Your agent_id — registered as creator + given the baton.")
    ] = "",
    creator_display_name: Annotated[
        str, Field(max_length=MCP_NAME_MAX, description="Your display name (optional).")
    ] = "",
    sequence_run_id: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description=(
                "Chain conductors only: the run UUID this thread is the coordination hub for. "
                "Stamping it is what lets every sub-orchestrator find this hub via "
                "get_context(categories=['chain']) — no subject convention required."
            ),
        ),
    ] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if subject:
        kwargs["subject"] = subject
    if severity:
        kwargs["severity"] = severity
    if product_id:
        kwargs["product_id"] = product_id
    if project_id:
        kwargs["project_id"] = project_id
    if creator_id:
        kwargs["creator_id"] = creator_id
    if creator_display_name:
        kwargs["creator_display_name"] = creator_display_name
    if sequence_run_id:
        kwargs["sequence_run_id"] = sequence_run_id
    result = await _call_tool(ctx, "create_thread", kwargs)
    # NOTE: best-effort WS broadcast so an agent-created thread auto-appears on the
    # dashboard, exactly like the user/REST create path (comm_threads.py). Without
    # this the chat is written to the DB but the Hub only shows it on a manual reload.
    try:
        from api.app_state import state as _state

        if _state.websocket_manager:
            tenant_key = _base._resolve_tenant(ctx)
            await broadcast_thread_update(
                _state.websocket_manager,
                tenant_key,
                thread_id=result.get("thread_id", ""),
                chat_id=result.get("chat_id", ""),
                status=result.get("status", "open"),
                next_action_owner=result.get("next_action_owner"),
                update_type="created",
            )
    except Exception:  # noqa: BLE001 - WS failure is non-fatal; result is already committed
        logger.debug("MCP create_thread WS broadcast failed (non-fatal)", exc_info=True)
    return result


@mcp.tool(
    title="Join Thread",
    description=(
        "Join a message-board thread by its thread_id, declaring/claiming your agent_id. "
        "Collision-safe (re-joining is a no-op). Registers you in the participant directory "
        "so broadcast posts reach you. "
        f"{branding.TWO_HUB_DISAMBIGUATION}"
    ),
    annotations=_tool_hints("join_thread"),
)
async def join_thread(
    thread_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="The thread UUID to join.")],
    agent_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Your agent_id (the identity you claim).")],
    display_name: Annotated[str, Field(max_length=MCP_NAME_MAX, description="Your display name (optional).")] = "",
    role: Annotated[str, Field(max_length=MCP_ID_MAX, description="Optional role label.")] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "thread_id": thread_id,
        "agent_id": agent_id,
        # BE-9289a: the harness is DETECTED from the MCP handshake, never declared. This
        # is the same resolver the render path uses (_detected_harness -> BE-9035b
        # harness_from_client_info), so no local instruction file can change what the
        # Hub shows. Absent/unknown clientInfo degrades to 'generic'.
        "detected_harness": _detected_harness(ctx),
    }
    if display_name:
        kwargs["display_name"] = display_name
    if role:
        kwargs["role"] = role
    return await _call_tool(ctx, "join_thread", kwargs)


@mcp.tool(
    title="Post to Thread",
    description=(
        "Post a message to a thread (append-only) -- the canonical agent-to-agent messaging "
        "tool. Broadcasts by default; see to_participant, set_status, from_agent, and "
        "pass_baton_to for DM, status, attribution, and atomic baton hand-off. "
        f"{branding.TWO_HUB_DISAMBIGUATION}"
    ),
    annotations=_tool_hints("post_to_thread"),
)
async def post_to_thread(
    thread_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="The thread UUID.")],
    content: Annotated[str, Field(max_length=MCP_MESSAGE_MAX, description="Message body.")],
    from_agent: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description="Your agent role/id from your activated template (e.g. implementer, tester, "
            "reviewer). Drives the Hub author badge. Omit ONLY if posting as the human user.",
        ),
    ] = "",
    to_participant: Annotated[
        str, Field(max_length=MCP_ID_MAX, description="Direct-message this participant_id. Omit to broadcast.")
    ] = "",
    set_status: Annotated[
        Literal["", "open", "active", "resolved", "closed"],
        Field(description="Optionally set the thread status with this post. Empty = unchanged."),
    ] = "",
    requires_action: Annotated[
        bool, Field(description="True if a recipient must act. Default false (informational).")
    ] = False,
    loop_directive: Annotated[
        bool,
        Field(
            description="Arm a loop/sleep directive: addressed agents are told to loop on this thread "
            "(checking get_my_turn/get_thread_history every N min) until it is resolved or closed."
        ),
    ] = False,
    loop_interval_minutes: Annotated[
        int,
        Field(
            ge=0,
            le=1440,
            description="Auto-check-in cadence in minutes for the loop directive. Surfaced on the "
            "get_my_turn/get_thread_history poll responses so the agent self-schedules its wake. "
            "0 = unset (agent uses its default). Only meaningful with loop_directive=true.",
        ),
    ] = 0,
    pass_baton_to: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description="Atomically hand the baton (next_action_owner) with this post: an agent_id "
            "| user_id | 'all' | 'none'. Explicit value always wins; 'none' posts WITHOUT moving "
            "the baton. DEFAULT when omitted: a directed action-request (requires_action=true + "
            "to_participant) auto-passes the baton to that participant; every other post leaves "
            "the baton untouched.",
        ),
    ] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "thread_id": thread_id,
        "content": content,
        "requires_action": requires_action,
        "loop_directive": loop_directive,
        "user_id": _base._resolve_user_id(ctx),
        # BE-9289a: server-detected harness, stamped onto the poster's participant row.
        "detected_harness": _detected_harness(ctx),
    }
    if from_agent:
        kwargs["from_agent"] = from_agent
    if to_participant:
        kwargs["to_participant"] = to_participant
    if set_status:
        kwargs["set_status"] = set_status
    if loop_interval_minutes:
        kwargs["loop_interval_minutes"] = loop_interval_minutes
    # BE-9197: the auto-pass rule lives in _resolve_pass_baton_to (module top).
    effective_baton_to = _resolve_pass_baton_to(pass_baton_to, requires_action, to_participant)
    if effective_baton_to:
        kwargs["pass_baton_to"] = effective_baton_to
    result = await _call_tool(ctx, "post_to_thread", kwargs)
    # BE-9292a: a refused hand-off is not a post. Nothing was persisted, so the
    # follow-on side effects below must not run — reactivation would block a recipient
    # over a message that does not exist, and the WS fan-out would announce it to the
    # Hub. Return the domain rejection untouched.
    if result.get("success") is False:
        return result
    # BE-9012b (D5): relocate the bus auto-block/reactivation onto project-bound Hub
    # posts. A directed (to_participant), action-required post on a project-bound
    # thread flips a completed recipient -> blocked (reactivation), exactly as the bus
    # did. Town-square / informational / broadcast posts are inert — the guards live
    # in auto_block_for_thread_post. Best-effort: the post is already committed and
    # authoritative; a rare failure here is logged (WARNING) and self-heals on the
    # next directed post rather than failing the agent's successful post.
    if requires_action and to_participant:
        try:
            accessor = _base._get_tool_accessor()
            outcome = await accessor._message_routing_service.auto_block_for_thread_post(
                message_id=result.get("message_id", ""),
                to_participant=to_participant,
                sender_display_name=result.get("from_display_name", from_agent or "orchestrator"),
                requires_action=requires_action,
                tenant_key=_base._resolve_tenant(ctx),
            )
            # BE-9247: surface the forward-on-send outcome in the SAME response so the
            # sender learns immediately (e.g. "Tester was closed -- your message was
            # forwarded to the orchestrator"), rather than discarding it silently.
            if outcome.notice:
                result["forward_notice"] = outcome.notice
        except Exception:  # noqa: BLE001 - reactivation is a follow-on side-effect; never unwind a durable post
            logger.warning(
                "MCP post_to_thread reactivation auto-block (D5) failed for message %s -> %s (non-fatal)",
                result.get("message_id", ""),
                to_participant,
                exc_info=True,
            )
    # NOTE: best-effort WS broadcast so agent posts also push live to the dashboard.
    try:
        from api.app_state import state as _state

        if _state.websocket_manager:
            tenant_key = _base._resolve_tenant(ctx)
            await broadcast_thread_message(
                _state.websocket_manager,
                tenant_key,
                thread_id=thread_id,
                message_id=result.get("message_id", ""),
                from_agent_id=result.get("from_agent_id", from_agent or ""),
                from_display_name=result.get("from_display_name", from_agent or "agent"),
                from_kind=result.get("from_kind", "agent"),  # BE-9289a
                content=content,
                message_type="direct" if to_participant else "broadcast",
                priority="normal",
                requires_action=requires_action,
                project_id=None,
            )
    except Exception:  # noqa: BLE001 - WS failure is non-fatal; result is already committed
        logger.debug("MCP post_to_thread WS broadcast failed (non-fatal)", exc_info=True)
    # BE-9197: when this post atomically moved the baton, push the SAME live
    # thread_update a standalone pass_baton pushes (update_type="baton", same
    # payload shape — parity is boundary-tested) so the Hub UI reflects the
    # hand-off identically whichever path moved it. Emitted after the message
    # event, mirroring the post-then-pass two-call sequence.
    if result.get("baton_passed"):
        try:
            from api.app_state import state as _state

            if _state.websocket_manager:
                tenant_key = _base._resolve_tenant(ctx)
                accessor = _base._get_tool_accessor()
                history = await accessor._comm_thread_service.get_thread_history(
                    thread_id=thread_id, tenant_key=tenant_key
                )
                t = history["thread"]
                await broadcast_thread_update(
                    _state.websocket_manager,
                    tenant_key,
                    thread_id=thread_id,
                    chat_id=t["chat_id"],
                    status=t["status"],
                    next_action_owner=result.get("next_action_owner"),
                    update_type="baton",
                )
        except Exception:  # noqa: BLE001 - WS failure is non-fatal; result is already committed
            logger.debug("MCP post_to_thread baton WS broadcast failed (non-fatal)", exc_info=True)
    return result


@mcp.tool(
    title="Get My Turn",
    description=(
        "The baton query: list threads where it is YOUR turn (next_action_owner == your "
        "agent_id, plus threads addressed to 'all'). Poll this to find conversations awaiting you. "
        f"{branding.TWO_HUB_DISAMBIGUATION}"
    ),
    annotations=_tool_hints("get_my_turn"),
)
async def get_my_turn(
    agent_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Your agent_id.")],
    ctx: Context = None,
) -> dict[str, Any]:
    return await _call_tool(ctx, "get_my_turn", {"agent_id": agent_id})


@mcp.tool(
    title="Pass Baton",
    description=(
        "Pass the baton: set who acts next on a thread. 'to' is an agent_id, a user_id, "
        "'all' (anyone), or 'none' (no one waiting). The recipient finds it via get_my_turn. "
        f"{branding.TWO_HUB_DISAMBIGUATION}"
    ),
    annotations=_tool_hints("pass_baton"),
)
async def pass_baton(
    thread_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="The thread UUID.")],
    to: Annotated[str, Field(max_length=MCP_ID_MAX, description="Next owner: an agent_id | user_id | 'all' | 'none'.")],
    ctx: Context = None,
) -> dict[str, Any]:
    result = await _call_tool(ctx, "pass_baton", {"thread_id": thread_id, "to": to})
    # BE-9292a: a refused hand-off moved no baton — broadcasting would tell the Hub the
    # owner had been cleared when it is unchanged.
    if result.get("success") is False:
        return result
    # NOTE: best-effort WS broadcast so MCP baton-passes also push live to the dashboard.
    try:
        from api.app_state import state as _state

        if _state.websocket_manager:
            from giljo_mcp.tools.tool_accessor import ToolAccessor

            tenant_key = _base._resolve_tenant(ctx)
            accessor: ToolAccessor = _base._get_tool_accessor()
            # BE-6118: the pure get_thread_history pass-through was removed from
            # ToolAccessor; call the owning terminal service directly (the same
            # target _call_tool dispatches to via TOOL_DISPATCH).
            history = await accessor._comm_thread_service.get_thread_history(thread_id=thread_id, tenant_key=tenant_key)
            t = history["thread"]
            await broadcast_thread_update(
                _state.websocket_manager,
                tenant_key,
                thread_id=thread_id,
                chat_id=t["chat_id"],
                status=t["status"],
                next_action_owner=result.get("next_action_owner"),
                update_type="baton",
            )
    except Exception:  # noqa: BLE001 - WS failure is non-fatal; result is already committed
        logger.debug("MCP pass_baton WS broadcast failed (non-fatal)", exc_info=True)
    return result


@mcp.tool(
    title="List Threads",
    description=(
        "List message-board threads with optional filters: status, owner (next_action_owner), "
        "product_id, project_id. Newest first. "
        f"{branding.TWO_HUB_DISAMBIGUATION}"
    ),
    annotations=_tool_hints("list_threads"),
)
async def list_threads(
    status: Annotated[str, Field(max_length=MCP_ID_MAX, description="Filter by status. Optional.")] = "",
    owner: Annotated[str, Field(max_length=MCP_ID_MAX, description="Filter by next_action_owner. Optional.")] = "",
    product_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Filter by product UUID. Optional.")] = "",
    project_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="Filter by project UUID. Optional.")] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if status:
        kwargs["status"] = status
    if owner:
        kwargs["owner"] = owner
    if product_id:
        kwargs["product_id"] = product_id
    if project_id:
        kwargs["project_id"] = project_id
    return await _call_tool(ctx, "list_threads", kwargs)


@mcp.tool(
    title="Get Thread History",
    description=(
        "Read a thread's message timeline, oldest-first. READ-ONLY by default (does NOT "
        "acknowledge; pass mark_read=true to do so). See tail/after_message_id/since for "
        "polling and as_participant for the persistent per-participant read cursor. "
        f"{branding.TWO_HUB_DISAMBIGUATION}"
    ),
    meta=MCP_HEAVY_TOOL_META,  # BE-9083c: raise Claude Code's inline-truncation ceiling
    # BE-9251 audit F2: read-scoped for auth (TOOL_SCOPES=mcp:read) but
    # mark_read=true is a real write -- _READ_SCOPED_BUT_MUTATING flips
    # readOnlyHint=False; destructive=False because that write is additive/
    # idempotent (draining an unread cursor), never deletes data.
    annotations=_tool_hints("get_thread_history", destructive=False),
)
async def get_thread_history(
    thread_id: Annotated[str, Field(max_length=MCP_ID_MAX, description="The thread UUID.")],
    after_message_id: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description="Incremental cursor: return only messages AFTER this message id. Omit for full timeline.",
        ),
    ] = "",
    since: Annotated[
        str,
        Field(
            max_length=MCP_SHORT_TEXT_MAX,
            description="Incremental: ISO-8601 timestamp; return only messages created after it. Omit for full timeline.",
        ),
    ] = "",
    tail: Annotated[
        int,
        Field(
            ge=-1,
            le=500,
            description="How many recent messages to return. Omit for the default bounded poll "
            f"(last {DEFAULT_HISTORY_TAIL}); pass 0 for the FULL timeline; pass 1..500 for the "
            "last N. The bounded default is not applied to an after_message_id/since/unread_only "
            "read (those already return only their delta).",
        ),
    ] = -1,
    as_participant: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description="Your participant_id — REQUIRED to use unread_only/mark_read/directed_only/"
            "action_required_only (the server-persistent cursor is per participant). Omit for a plain read.",
        ),
    ] = "",
    unread_only: Annotated[
        bool,
        Field(description="Return only posts since your last mark_read on this thread. Requires as_participant."),
    ] = False,
    mark_read: Annotated[
        bool,
        Field(
            description="Acknowledge the returned posts and advance your persistent read cursor "
            "(on a clean unread drain). Requires as_participant; join_thread first. This is a WRITE."
        ),
    ] = False,
    directed_only: Annotated[
        bool,
        Field(
            description="Return only posts delivered to you (DMs + broadcasts you received; excludes a DM aimed at someone else). Requires as_participant."
        ),
    ] = False,
    action_required_only: Annotated[
        bool,
        Field(description="Return only posts flagged requires_action. Requires as_participant."),
    ] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"thread_id": thread_id}
    if after_message_id:
        kwargs["after_message_id"] = after_message_id
    if since:
        kwargs["since"] = since
    # BE-9061: bound the DEFAULT plain poll (the hot loop_directive read). tail>0
    # is honored as-is; tail==0 is the explicit FULL timeline (forward nothing);
    # tail omitted (-1) applies DEFAULT_HISTORY_TAIL, but ONLY on a plain read —
    # an after_message_id/since/unread_only read is already a delta and truncating
    # it would (for unread_only+mark_read) stall the read cursor.
    if tail > 0:
        kwargs["tail"] = tail
    elif tail < 0 and not (after_message_id or since or unread_only or mark_read):
        kwargs["tail"] = DEFAULT_HISTORY_TAIL
    # BE-9012a: forward as_participant + the cursor flags. Flags are forwarded even
    # without as_participant so the owning service raises the clean 422 (required-param)
    # rather than the wrapper silently dropping them.
    if as_participant:
        kwargs["as_participant"] = as_participant
    if unread_only:
        kwargs["unread_only"] = True
    if mark_read:
        kwargs["mark_read"] = True
    if directed_only:
        kwargs["directed_only"] = True
    if action_required_only:
        kwargs["action_required_only"] = True
    result = await _call_tool(ctx, "get_thread_history", kwargs)
    # BE-9012b (D5, §6 row 10): surface the "how to exit blocked" guidance to an
    # auto-blocked reader on the cursor read, the way the bus drain-read did. Only when
    # the reader self-identifies (as_participant) and is post-completion auto-blocked;
    # returns nothing otherwise. Best-effort — never fail a read over the hint.
    if as_participant and isinstance(result, dict):
        try:
            accessor = _base._get_tool_accessor()
            guidance = await accessor._agent_state_service.reactivation_guidance_for_agent(
                as_participant, _base._resolve_tenant(ctx)
            )
            if guidance:
                result["reactivation_guidance"] = guidance
        except Exception:  # noqa: BLE001 - guidance is an advisory hint; never fail the read
            logger.debug("get_thread_history reactivation guidance (D5) failed (non-fatal)", exc_info=True)
    # FE-9184: a mark_read drain writes message_acknowledgments, which decrements
    # the /jobs "Messages Waiting" badge — push a live thread_update so the
    # dashboard refreshes without waiting for the next post. Emit ONLY when acks
    # were actually written (marked_read > 0: a plain read, an already-drained
    # cursor, and the NOT_A_PARTICIPANT rejection all skip). Best-effort like
    # every hub WS emit — the acks are already committed.
    if (
        mark_read
        and isinstance(result, dict)
        and result.get("success") is not False
        and result.get("marked_read", 0) > 0
    ):
        try:
            from api.app_state import state as _state

            if _state.websocket_manager:
                t = result.get("thread") or {}
                await broadcast_thread_update(
                    _state.websocket_manager,
                    _base._resolve_tenant(ctx),
                    thread_id=thread_id,
                    chat_id=t.get("chat_id", ""),
                    status=t.get("status", "open"),
                    next_action_owner=t.get("next_action_owner"),
                    update_type="read",
                )
        except Exception:  # noqa: BLE001 - WS failure is non-fatal; the drain already committed
            logger.debug("MCP get_thread_history mark_read WS broadcast failed (non-fatal)", exc_info=True)
    return result


@mcp.tool(
    title="Search Threads",
    description=(
        "Search threads by CHT serial, subject keyword, participant, or message content. "
        "Tenant-scoped, newest first. Used by /giljo to find a chat. "
        f"{branding.TWO_HUB_DISAMBIGUATION}"
    ),
    annotations=_tool_hints("search_threads"),
)
async def search_threads(
    query: Annotated[
        str, Field(max_length=MCP_SHORT_TEXT_MAX, description="CHT-#### serial, subject keyword, participant, or text.")
    ],
    ctx: Context = None,
) -> dict[str, Any]:
    return await _call_tool(ctx, "search_threads", {"query": query})
