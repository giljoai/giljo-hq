# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager, tenant_session_context
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.harness_resolver import GENERIC_HARNESS
from giljo_mcp.models.comm import (
    BOUND_THREAD_MARKER_SUBJECT,
    LOOP_DIRECTIVE_MESSAGE_TYPE,
    TERMINAL_THREAD_STATUSES,
    VALID_PARTICIPANT_TYPES,
    CommParticipant,
    CommThread,
)
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository
from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.repositories.user_repository import UserRepository
from giljo_mcp.schemas.comm_serializers import message_dict, thread_dict
from giljo_mcp.services._comm_thread_baton_mixin import CommThreadBatonMixin
from giljo_mcp.services._comm_thread_chain_hub_mixin import CommThreadChainHubMixin
from giljo_mcp.services._comm_thread_create_binding_mixin import CommThreadCreateBindingMixin
from giljo_mcp.services._comm_thread_edit_mixin import CommThreadEditMixin
from giljo_mcp.services._comm_thread_liveness_mixin import (
    CommThreadLivenessMixin,
    _build_skipped_recipients_notice,
)
from giljo_mcp.services._comm_thread_operator_read_mixin import CommThreadOperatorReadMixin
from giljo_mcp.services._comm_thread_softdelete_mixin import CommThreadSoftDeleteMixin
from giljo_mcp.services._comm_thread_wake_mixin import CommThreadWakeMixin
from giljo_mcp.services.comm_author_identity import resolve_and_register_author, validate_post_author_input
from giljo_mcp.services.comm_baton_targets import (
    HubTargetRefusedError,
    broadcast_reply_should_clear_baton,
    enrol_addressee,
    post_target_rejection,
    resolve_operator_alias,
)
from giljo_mcp.services.comm_post_validation import resolve_loop_interval, validate_post_vocabularies
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)

_FROM_AGENT_MAX = 64

_TAIL_MIN = 1
_TAIL_MAX = 500

_NARROWED_MARK_READ_NOTE = (
    "Acknowledged exactly the posts returned, but the per-participant read cursor did "
    "NOT advance: this read was narrowed (directed_only / action_required_only) or "
    "truncated (tail / after_message_id / since), so the returned set is not the "
    "contiguous run up to the newest post and advancing would skip what it excluded. "
    "unread_only will keep returning these posts until you re-read the thread with "
    "as_participant + mark_read=true and NO filters."
)


class CommThreadService(
    CommThreadChainHubMixin,
    CommThreadOperatorReadMixin,
    CommThreadCreateBindingMixin,
    CommThreadSoftDeleteMixin,
    CommThreadEditMixin,
    CommThreadBatonMixin,
    CommThreadWakeMixin,
    CommThreadLivenessMixin,
):

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_manager: TenantManager,
        session: AsyncSession | None = None,
    ) -> None:
        self._db_manager = db_manager
        self._tenant_manager = tenant_manager
        self._session = session
        self._repo = CommThreadRepository()
        self._user_repo = UserRepository()
        self._agent_ops = AgentOperationsRepository()


    def _resolve_tenant(self, tenant_key: str | None) -> str:
        tk = tenant_key or self._tenant_manager.get_current_tenant()
        if not tk:
            raise ValidationError("tenant_key is required", context={"operation": "comm_thread"})
        return tk

    @asynccontextmanager
    async def _scoped_session(self, tenant_key: str):
        if self._session is not None:
            with tenant_session_context(self._session, tenant_key):
                yield self._session
        else:
            async with self._db_manager.get_session_async(tenant_key=tenant_key) as session:
                with tenant_session_context(session, tenant_key):
                    yield session

    async def _require_thread(self, session: AsyncSession, tenant_key: str, thread_id: str) -> CommThread:
        thread = await self._repo.get_by_id(session, tenant_key, thread_id)
        if thread is None:
            raise ResourceNotFoundError(
                message="Thread not found or access denied",
                context={"operation": "comm_thread", "thread_id": thread_id},
            )
        return thread


    async def create_thread(
        self,
        *,
        subject: str | None = None,
        severity: str | None = None,
        product_id: str | None = None,
        project_id: str | None = None,
        creator_id: str | None = None,
        creator_type: str = "agent",
        creator_display_name: str | None = None,
        sequence_run_id: str | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        tk = self._resolve_tenant(tenant_key)
        if creator_type not in VALID_PARTICIPANT_TYPES:
            raise ValidationError(
                f"Unknown creator_type {creator_type!r}. Valid: {sorted(VALID_PARTICIPANT_TYPES)}",
                context={"operation": "comm_thread.create"},
            )
        async with self._scoped_session(tk) as session:
            if not product_id:
                product_id = await self._resolve_create_product_id(
                    session, tk, project_id=project_id, sequence_run_id=sequence_run_id
                )
            thread = await self._repo.create_thread(
                session,
                tk,
                subject=subject,
                severity=severity,
                product_id=product_id,
                project_id=project_id,
                next_action_owner=creator_id,
                sequence_run_id=sequence_run_id,
            )
            if creator_id:
                await self._repo.add_participant(
                    session,
                    tk,
                    thread.id,
                    participant_id=creator_id,
                    participant_type=creator_type,
                    display_name=creator_display_name,
                    role="creator",
                )
            return thread_dict(thread)

    async def resolve_or_create_bound_thread(self, *, project_id: str, tenant_key: str | None = None) -> dict[str, Any]:
        tk = self._resolve_tenant(tenant_key)
        async with self._scoped_session(tk) as session:
            thread = await self._repo.resolve_or_create_bound_thread(
                session, tk, project_id, marker=BOUND_THREAD_MARKER_SUBJECT
            )
            return thread_dict(thread)

    async def join_thread(
        self,
        *,
        thread_id: str,
        participant_id: str,
        participant_type: str = "agent",
        display_name: str | None = None,
        role: str | None = None,
        detected_harness: str | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        tk = self._resolve_tenant(tenant_key)
        if not participant_id:
            raise ValidationError("participant_id is required", context={"operation": "comm_thread.join"})
        async with self._scoped_session(tk) as session:
            await self._require_thread(session, tk, thread_id)
            participant = await self._repo.add_participant(
                session,
                tk,
                thread_id,
                participant_id=participant_id,
                participant_type=participant_type,
                display_name=display_name,
                role=role,
                harness=detected_harness or GENERIC_HARNESS,
                touch_last_seen=True,
                authoritative=True,
            )
            return {
                "participant_id": participant.participant_id,
                "thread_id": thread_id,
                "participant_type": participant.participant_type,
            }

    async def _rename_before_post(self, thread_id: str, rename_to: str | None, tenant_key: str) -> None:
        if rename_to is not None:
            await self.update_thread(thread_id=thread_id, subject=rename_to, tenant_key=tenant_key)

    async def post_to_thread(
        self,
        *,
        thread_id: str,
        content: str,
        from_agent: str | None = None,
        to_participant: str | None = None,
        message_type: str = "direct",
        priority: str = "normal",
        requires_action: bool = False,
        set_status: str | None = None,
        loop_directive: bool = False,
        loop_interval_minutes: int | None = None,
        pass_baton_to: str | None = None,
        clear_baton_on_broadcast_reply: bool = False,
        user_id: str | None = None,
        as_user: bool = False,
        detected_harness: str | None = None,
        self_reported_status: str | None = None,
        rename_to: str | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        tk = self._resolve_tenant(tenant_key)
        if not content or not content.strip():
            raise ValidationError("content is required", context={"operation": "comm_thread.post"})
        validate_post_vocabularies(set_status, self_reported_status)
        await self._rename_before_post(thread_id, rename_to, tk)
        interval_to_persist = resolve_loop_interval(loop_directive, loop_interval_minutes)

        from_agent = validate_post_author_input(from_agent, as_user, _FROM_AGENT_MAX)

        async with self._scoped_session(tk) as session:
            thread = await self._require_thread(session, tk, thread_id)

            to_participant = (
                await resolve_operator_alias(self._user_repo, session, tk, to_participant) or to_participant
            )
            pass_baton_to = await resolve_operator_alias(self._user_repo, session, tk, pass_baton_to) or pass_baton_to

            rejection = await post_target_rejection(
                self._repo,
                self._user_repo,
                session,
                tk,
                thread_id,
                to_participant=to_participant,
                pass_baton_to=pass_baton_to,
                author_id=from_agent or user_id,
                current_owner=thread.next_action_owner,
            )
            if rejection is not None:
                raise HubTargetRefusedError(rejection)

            baton_passed = baton_cleared = False
            if pass_baton_to and pass_baton_to != "none":
                await self._repo.set_next_action_owner(session, tk, thread_id, pass_baton_to)
                baton_passed = True
            elif broadcast_reply_should_clear_baton(
                clear_baton_on_broadcast_reply, to_participant, thread.next_action_owner, user_id
            ):
                await self._repo.set_next_action_owner(session, tk, thread_id, None)
                baton_cleared = True

            author = await resolve_and_register_author(
                self._repo,
                self._user_repo,
                session,
                tk,
                thread_id,
                from_agent=from_agent,
                user_id=user_id,
                detected_harness=detected_harness,
                as_user=as_user,
                self_reported_status=self_reported_status,
            )
            from_agent_id, from_kind = author.agent_id, author.kind
            from_display_name, attribution_warning = author.display_name, author.warning

            recipient_ids, skipped_recipients, candidate_count = await self._resolve_recipients(
                session,
                tk,
                thread,
                to_participant=to_participant,
                from_agent_id=from_agent_id,
                requires_action=requires_action,
            )

            if loop_directive:
                resolved_message_type = LOOP_DIRECTIVE_MESSAGE_TYPE
            elif to_participant:
                resolved_message_type = message_type
            else:
                resolved_message_type = "broadcast"

            message = await self._repo.persist_thread_message(
                session,
                tenant_key=tk,
                thread_id=thread_id,
                project_id=thread.project_id,
                content=content,
                from_agent_id=from_agent_id,
                from_display_name=from_display_name,
                from_kind=from_kind,
                message_type=resolved_message_type,
                priority=priority,
                requires_action=requires_action,
                recipient_ids=recipient_ids,
                loop_interval_minutes=interval_to_persist,
            )
            if set_status is not None:
                await self._repo.set_status(session, tk, thread_id, set_status)
            notice = await self.collect_handover_notice(
                session, tk, thread, pass_baton_to if baton_passed else None, from_display_name
            )
            result = {
                "message_id": message.id,
                "thread_id": thread_id,
                "recipients": recipient_ids,
                "to_participant": to_participant,
                "from_agent_id": from_agent_id,
                "from_display_name": from_display_name,
                "from_kind": from_kind,
                "attribution_warning": attribution_warning,
                "loop_directive_armed": loop_directive,
                "loop_interval_minutes": interval_to_persist,
                "baton_passed": baton_passed,
                "baton_cleared": baton_cleared,
                "next_action_owner": thread.next_action_owner,
                **self._post_advice_entry(
                    set_status, content=content, requires_action=requires_action, baton_passed=baton_passed
                ),
            }
            skipped_notice = _build_skipped_recipients_notice(
                skipped_recipients, recipient_ids, candidate_count, is_broadcast=not to_participant
            )
            if skipped_notice:
                result["skipped_recipients"] = skipped_notice
                result["skipped_recipient_details"] = skipped_recipients

        self._signal_post_wake(tk, to_participant, requires_action, pass_baton_to, baton_passed, recipient_ids)
        await self.emit_handover_notice(notice)
        return result

    async def list_threads(
        self,
        *,
        status: str | None = None,
        owner: str | None = None,
        product_id: str | None = None,
        project_id: str | None = None,
        limit: int | None = None,
        before_id: str | None = None,
        viewer_id: str | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        tk = self._resolve_tenant(tenant_key)
        async with self._scoped_session(tk) as session:
            threads = await self._repo.list_threads(
                session,
                tk,
                status=status,
                next_action_owner=owner,
                product_id=product_id,
                project_id=project_id,
                limit=limit,
                before_id=before_id,
            )
            payload = [thread_dict(t) for t in threads]
            if viewer_id:
                facts = await self._repo.list_threads_enriched(session, tk, viewer_id=viewer_id, threads=threads)
                for entry in payload:
                    entry.update(facts.get(entry["thread_id"], {}))
            return {"count": len(threads), "threads": payload}

    async def _apply_mark_read(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        participant: CommParticipant,
        as_participant: str,
        messages: list,
        narrowed: bool,
    ) -> tuple[int, bool]:
        marked_read = await self._repo.ack_messages_for_participant(
            session, tenant_key, agent_id=as_participant, message_ids=[m.id for m in messages]
        )
        if narrowed:
            return marked_read, False
        newest = messages[-1]
        if newest.created_at is not None and (
            participant.last_read_at is None or newest.created_at > participant.last_read_at
        ):
            participant.last_read_message_id = newest.id
            participant.last_read_at = newest.created_at
            await session.flush()
            return marked_read, True
        return marked_read, False

    async def get_thread_history(
        self,
        *,
        thread_id: str,
        after_message_id: str | None = None,
        since: str | None = None,
        tail: int | None = None,
        as_participant: str | None = None,
        unread_only: bool = False,
        mark_read: bool = False,
        directed_only: bool = False,
        action_required_only: bool = False,
        include_recipient_state: bool = False,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        if after_message_id and since:
            raise ValidationError(
                "Pass at most one of 'after_message_id' or 'since' (both name a start marker).",
                context={"operation": "comm_thread.history", "thread_id": thread_id},
            )

        if (unread_only or mark_read or directed_only or action_required_only) and not as_participant:
            raise ValidationError(
                "as_participant is required when using unread_only / mark_read / "
                "directed_only / action_required_only (the per-participant cursor "
                "must know who is reading).",
                context={"operation": "comm_thread.history", "thread_id": thread_id},
            )

        since_dt: datetime | None = None
        if since:
            try:
                since_dt = datetime.fromisoformat(since)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    "'since' must be an ISO-8601 timestamp (e.g. a message's created_at).",
                    context={"operation": "comm_thread.history", "since": since},
                ) from exc

        if tail is not None:
            if not isinstance(tail, int) or isinstance(tail, bool):
                raise ValidationError(
                    "'tail' must be an integer number of messages.",
                    context={"operation": "comm_thread.history"},
                )
            if not (_TAIL_MIN <= tail <= _TAIL_MAX):
                raise ValidationError(
                    f"'tail' must be between {_TAIL_MIN} and {_TAIL_MAX}.",
                    context={"operation": "comm_thread.history", "tail": tail},
                )

        tk = self._resolve_tenant(tenant_key)
        async with self._scoped_session(tk) as session:
            thread = await self._require_thread(session, tk, thread_id)

            participant = None
            if as_participant:
                await self._repo.touch_participant_last_seen(session, tk, as_participant, thread_id=thread_id)
                participant = await self._repo.get_participant(session, tk, thread_id, as_participant)

            if mark_read and participant is None:
                delivered = await self._repo.get_thread_messages(
                    session, tk, thread_id, directed_to=as_participant, tail=1
                )
                if delivered:
                    participant = await enrol_addressee(
                        self._repo,
                        self._user_repo,
                        session,
                        tk,
                        thread_id,
                        as_participant,
                        touch_last_seen=True,
                    )
                else:
                    return {
                        "success": False,
                        "error": "NOT_A_PARTICIPANT",
                        "thread_id": thread_id,
                        "as_participant": as_participant,
                        "hint": "join_thread this thread first (re-joining is a safe no-op), then retry mark_read.",
                    }

            unread_after = participant.last_read_at if (unread_only and participant is not None) else None
            directed_to = as_participant if directed_only else None

            messages = await self._repo.get_thread_messages(
                session,
                tk,
                thread_id,
                after_message_id=after_message_id or None,
                since=since_dt,
                tail=tail,
                unread_after=unread_after,
                directed_to=directed_to,
                action_required_only=action_required_only,
            )

            narrowed = bool(directed_only or action_required_only or tail or after_message_id or since)
            marked_read = 0
            cursor_advanced = False
            if mark_read and participant is not None and messages:
                marked_read, cursor_advanced = await self._apply_mark_read(
                    session,
                    tk,
                    participant=participant,
                    as_participant=as_participant,
                    messages=messages,
                    narrowed=narrowed,
                )

            recipient_state: dict[str, dict[str, list[str]]] = {}
            if include_recipient_state and messages:
                recipient_state = await self._repo.get_recipient_state_for_messages(
                    session, tk, message_ids=[m.id for m in messages]
                )

            directive = await self._repo.get_latest_loop_directive(session, tk, thread_id)
            active = directive is not None and not self.is_terminal_status(thread.status)
            response = {
                "thread": thread_dict(thread),
                "count": len(messages),
                "messages": [
                    message_dict(m, recipient_state.get(m.id) if include_recipient_state else None) for m in messages
                ],
                "loop_directive": {
                    "active": active,
                    "interval_minutes": directive.loop_interval_minutes if (directive and active) else None,
                },
            }
            if mark_read:
                response["marked_read"] = marked_read
                response["cursor_advanced"] = cursor_advanced
                if messages and narrowed:
                    response["mark_read_note"] = _NARROWED_MARK_READ_NOTE
            return response

    async def search_threads(self, *, query: str, limit: int = 50, tenant_key: str | None = None) -> dict[str, Any]:
        tk = self._resolve_tenant(tenant_key)
        if not query or not query.strip():
            raise ValidationError("query is required", context={"operation": "comm_thread.search"})
        async with self._scoped_session(tk) as session:
            threads = await self._repo.search_threads(session, tk, query, limit=limit)
            return {"query": query, "count": len(threads), "threads": [thread_dict(t) for t in threads]}

    async def list_participants(self, *, thread_id: str, tenant_key: str | None = None) -> dict[str, Any]:
        tk = self._resolve_tenant(tenant_key)
        async with self._scoped_session(tk) as session:
            await self._require_thread(session, tk, thread_id)
            parts = await self._repo.get_participants_with_status(session, tk, thread_id)
            return {
                "thread_id": thread_id,
                "count": len(parts),
                "participants": [
                    {
                        "participant_id": p.participant_id,
                        "participant_type": p.participant_type,
                        "display_name": p.display_name,
                        "role": p.role,
                        "harness": p.harness,
                        "last_seen_at": p.last_seen_at.isoformat() if p.last_seen_at else None,
                        "joined_at": p.joined_at.isoformat() if p.joined_at else None,
                        "status": status,
                    }
                    for p, status in parts
                ],
            }

    @staticmethod
    def is_terminal_status(status: str | None) -> bool:
        return status in TERMINAL_THREAD_STATUSES
