# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
MessageRoutingService - Hub reactivation coupling (BE-9012d) + forward-on-send (BE-9247).

BE-9012d (bus retirement, phase d): the bus send/broadcast/broadcast_to_project
methods (and their WS message:sent/received emitters) were HARD-REMOVED. This
service now carries only the piece of bus behavior that was relocated onto the
Hub in BE-9012b (D5): the message->lifecycle auto-block/reactivation coupling.

Responsibilities:
- Auto-blocking completed agents on a directed, action-required Hub post
  (``auto_block_for_thread_post``, called by the MCP wrapper + REST adapter
  after a successful ``post_to_thread``)
- The shared underlying auto-block primitive (``_auto_block_completed_recipients``)
- BE-9247: forward-on-send — a directed, action-required post addressed to an
  already-TERMINAL (closed/decommissioned) recipient is redirected to the live
  orchestrator at send time, reusing the SAME primitives P1/BE-9242 introduced
  for its close-time cursor sweep (``forward_action_required_to_orchestrator`` /
  ``build_forwarded_annotation``). A ``complete`` recipient keeps the pre-existing
  auto-block/reactivate behavior unchanged; any other status is inert.

CE-0026: staging broadcast directive detection (formerly Layer 5.5) removed.
The end-of-staging signal is now ``complete_job`` — see
``JobCompletionService._handle_staging_end``.
"""

import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.project_status import IMMUTABLE_PROJECT_STATUSES
from giljo_mcp.models.tasks import Message
from giljo_mcp.repositories.agent_completion_repository import AgentCompletionRepository
from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.repositories.message_repository import MessageRepository
from giljo_mcp.services._session_helpers import optional_tenant_session
from giljo_mcp.services.agent_terminal_cursor_service import forward_action_required_to_orchestrator
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

# BE-9247: the truly-dead subset that gets redirected at send time. 'complete'
# is deliberately excluded -- it keeps the pre-existing auto-block/reactivate
# path (design decision (a) in the work order), not a forward.
_TERMINAL_DEAD_STATUSES = frozenset({"closed", "decommissioned"})


class AutoBlockOutcome(list):
    """The list of auto-blocked agent_ids (``blocked == [...]`` still works), plus
    ``.notice`` (BE-9247): a sender-facing string set only on a send-time
    forward/self-forward/no-target outcome, never on the pre-existing
    auto-block/reactivate path.
    """

    def __init__(self, auto_blocked_ids: list[str] | None = None) -> None:
        super().__init__(auto_blocked_ids or [])
        self.notice: str | None = None


class MessageRoutingService:
    """
    Service carrying the Hub reactivation coupling (BE-9012d).

    Auto-blocks completed agents that receive a directed, action-required
    post on a project-bound Hub thread — the same lifecycle coupling the
    retired bus's ``send_message`` used to drive.

    Thread Safety: Each instance is session-scoped. Do not share across requests.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_manager: TenantManager,
        websocket_manager: Any | None = None,
        test_session: AsyncSession | None = None,
    ):
        """
        Initialize MessageRoutingService.

        Args:
            db_manager: Database manager for async database operations
            tenant_manager: Tenant manager for multi-tenancy support
            websocket_manager: Optional WebSocket manager for real-time event emissions
            test_session: Optional AsyncSession for tests to share the same transaction
        """
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._websocket_manager = websocket_manager
        self._test_session = test_session
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._repo = MessageRepository()

    def _get_session(self, tenant_key: str | None = None):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return optional_tenant_session(self.db_manager, tenant_key, self._test_session)

    async def _auto_block_completed_recipients(
        self,
        session: AsyncSession,
        resolved_to_agents: list[str],
        project: Any,
        sender_display_name: str,
        is_broadcast_fanout: bool,
        requires_action: bool = False,
        message: Message | None = None,
    ) -> AutoBlockOutcome:
        """Auto-block completed agents that receive a direct message (Handover 0827b);
        redirect an already-TERMINAL recipient's message to the live orchestrator
        (BE-9247, forward-on-send).

        Handover 0435d: Only auto-block if requires_action=True. Informational
        messages (requires_action=False) no longer trigger reactivation.

        BE-9247: a recipient whose latest execution is 'closed' or 'decommissioned'
        (``_TERMINAL_DEAD_STATUSES`` -- the truly-dead subset) is NEVER auto-blocked
        (there is nothing left to reactivate); instead the just-posted ``message`` is
        redirected to the live orchestrator via ``_redirect_terminal_recipient``. The
        pre-existing bus-fixture tests call this method directly with ``message=None``
        and never seed a dead recipient, so that branch is simply never reached for
        them. Any other status (live, working, blocked, ...) is unchanged: no
        auto-block, no forward.

        Returns:
            ``AutoBlockOutcome`` -- a list of auto-blocked agent_ids (compares equal
            to a plain list, e.g. ``blocked == [...]``, so every existing caller
            keeps working unchanged) plus an optional ``.notice`` sender-facing
            string when a BE-9247 redirect/self-forward/no-target situation
            produced one.
        """
        if is_broadcast_fanout:
            return AutoBlockOutcome()

        if not requires_action:
            return AutoBlockOutcome()

        # BE-5039 Phase 2b: derive the closed-project gate from the
        # canonical immutable-status set instead of duplicating the
        # tuple. ``IMMUTABLE_PROJECT_STATUSES`` is the str-mixin enum
        # frozenset {COMPLETED, CANCELLED}.
        if project.status in IMMUTABLE_PROJECT_STATUSES:
            return AutoBlockOutcome()

        # BE-9273 P2 audit finding: _redirect_terminal_recipient's rollback-on-DB-
        # failure (added for the forward-on-send fix) rolls back the WHOLE session
        # transaction, which would revert an EARLIER recipient's uncommitted flush
        # in this same loop if resolved_to_agents ever held more than one element.
        # The single production caller (auto_block_for_thread_post) always passes
        # exactly one; assert it rather than silently let that assumption drift --
        # multi-recipient batching would need per-recipient savepoint isolation
        # before this method could safely process more than one at a time.
        assert len(resolved_to_agents) <= 1, (
            "_auto_block_completed_recipients processes at most one recipient per "
            "call -- _redirect_terminal_recipient's rollback-on-failure is only "
            "transaction-safe for a single-element resolved_to_agents"
        )

        auto_blocked_ids = []
        # A list, not a single scalar: kept list-shaped for API stability (callers
        # compare ``blocked == [...]``) even though today's single recipient means
        # at most one entry is ever appended.
        notices: list[str] = []
        # BE-3008b: collect the status-change broadcasts and emit them AFTER the
        # commit, fire-and-forget. The old code awaited broadcast_job_status_update
        # inside the loop — i.e. BEFORE the commit below, while the flushed
        # status='blocked' row was lock-held — so a slow WS client convoyed the
        # transaction and a roll-back could leak a phantom 'blocked' event. The
        # broadcast now runs decoupled from the write path once the change is
        # durable.
        pending_broadcasts: list[dict[str, Any]] = []
        for recipient_id in resolved_to_agents:
            recipient_execution = await self._repo.get_execution_by_agent_id(session, project.tenant_key, recipient_id)

            # Handover 0435b: skip 'closed' agents — they are terminal, no auto-block
            if recipient_execution and recipient_execution.status == "complete":
                old_status = recipient_execution.status
                recipient_execution.status = "blocked"
                recipient_execution.block_reason = f"Received message from {sender_display_name} while completed"
                await self._repo.flush(session)

                auto_blocked_ids.append(recipient_id)

                if self._websocket_manager:
                    job_row = await self._repo.get_job_id_and_project_for_execution(
                        session, project.tenant_key, recipient_execution.job_id
                    )
                    pending_broadcasts.append(
                        {
                            "job_id": recipient_execution.job_id,
                            "agent_display_name": recipient_execution.agent_display_name,
                            "tenant_key": project.tenant_key,
                            "old_status": old_status,
                            "new_status": "blocked",
                            "project_id": str(job_row.project_id) if job_row else None,
                            "product_id": str(job_row.product_id) if job_row and job_row.product_id else None,
                        }
                    )

                self._logger.info(
                    f"[AUTO-BLOCK] Agent {sanitize(recipient_execution.agent_display_name)} "
                    f"({sanitize(recipient_id)}) auto-blocked: message from {sanitize(sender_display_name)}"
                )
            elif recipient_execution and recipient_execution.status in _TERMINAL_DEAD_STATUSES and message is not None:
                recipient_notice = await self._redirect_terminal_recipient(
                    session,
                    tenant_key=project.tenant_key,
                    project_id=project.id,
                    message=message,
                    dead_execution=recipient_execution,
                )
                notices.append(recipient_notice)

        if auto_blocked_ids:
            await session.commit()

            # BE-3008b: broadcast only after the block is durable, off the write
            # path. schedule() fire-and-forgets; if unavailable (older manager),
            # fall back to an inline awaited send so behaviour is never lost.
            if self._websocket_manager and pending_broadcasts:
                schedule = getattr(self._websocket_manager, "schedule", None)
                for kwargs in pending_broadcasts:
                    try:
                        coro = self._websocket_manager.broadcast_job_status_update(**kwargs)
                        if callable(schedule):
                            schedule(coro)
                        else:
                            await coro
                    except (RuntimeError, ValueError) as e:
                        self._logger.warning(
                            f"Failed to broadcast auto-block status change for {kwargs.get('job_id')}: {e}"
                        )

        outcome = AutoBlockOutcome(auto_blocked_ids)
        outcome.notice = "; ".join(notices) if notices else None
        return outcome

    async def _redirect_terminal_recipient(
        self,
        session: AsyncSession,
        *,
        tenant_key: str,
        project_id: str,
        message: Message,
        dead_execution: Any,
    ) -> str:
        """BE-9247: redirect a directed, action-required post off an already-TERMINAL
        (closed/decommissioned) recipient to the live orchestrator (single hop,
        never recurses on a terminal forward target), reusing P1/BE-9242's
        ``forward_action_required_to_orchestrator`` / ``build_forwarded_annotation``
        VERBATIM. Runs POST-COMMIT of the original post -- the dead recipient's
        ``MessageRecipient`` row already exists -- so a SUCCESSFUL forward also acks
        the dead agent's cursor for THIS message (mirrors
        ``resolve_terminal_agent_cursors``) so its unread does not linger. Never
        acks on anything less than a successful forward.

        Returns a sender-facing notice string -- every branch below produces one, so
        the sender is never left silently guessing what happened to their post.
        """
        completion_repo = AgentCompletionRepository()
        thread_repo = CommThreadRepository()
        dead_label = dead_execution.agent_display_name or dead_execution.agent_id
        # Shared prefix for every "nothing was forwarded" branch below, so the three
        # notice variants (no orchestrator / self-forward / forward failed) don't each
        # re-spell "RECIPIENT_FINISHED: {label} is finished ({status})".
        finished_prefix = f"RECIPIENT_FINISHED: {dead_label} is finished ({dead_execution.status})"

        live_orchestrator = await completion_repo.find_active_orchestrator_in_project(session, tenant_key, project_id)

        if live_orchestrator is None:
            logger.warning(
                "BE-9247: no live orchestrator to forward action-required message %s "
                "(dead recipient %s, project %s, status %s) -- leaving cursor unresolved",
                message.id,
                sanitize(dead_execution.agent_id),
                project_id,
                dead_execution.status,
            )
            thread = await thread_repo.get_by_id(session, tenant_key, message.thread_id) if message.thread_id else None
            fallback_owner = thread.next_action_owner if thread else None
            if fallback_owner:
                return (
                    f"{finished_prefix} and no live orchestrator was found to redirect to; "
                    f"{fallback_owner} currently holds this thread's baton."
                )
            return f"{finished_prefix} and no live orchestrator was found to redirect to."

        # Self-forward guard: the SENDER is frequently the orchestrator itself. Forwarding
        # a message to its own author would just re-deliver it to the agent who just
        # posted it -- notice-only, never a self-addressed forward. Match EVERY identity
        # the live orchestrator can legitimately self-declare with:
        #  - agent_id: its executor identity.
        #  - job_id: the shipped AGENT REACTIVATION PROTOCOL teaches orchestrators to
        #    post with from_agent="{orchestrator_id}", and {orchestrator_id} is the
        #    job_id (a DIFFERENT UUID from agent_id). Without this, a live orchestrator
        #    following its own protocol self-forwards to its own agent_id and gates its
        #    own complete_job (BE-9247 audit Finding 1).
        #  - agent_display_name / the literal "orchestrator": a post attributed with no
        #    identity at all (comm_thread_service.post_to_thread's from_agent_id fallback,
        #    both when neither from_agent nor a user posted) stamps the literal string
        #    "orchestrator" rather than a real agent_id -- the system already treats such
        #    a post as orchestrator-authored end to end (its from_display_name gets the
        #    same literal), so match that fallback too.
        orchestrator_identities = {
            live_orchestrator.agent_id,
            live_orchestrator.job_id,
            live_orchestrator.agent_display_name,
            "orchestrator",
        }
        if message.from_agent_id in orchestrator_identities:
            return f"{finished_prefix}; you are the live orchestrator for this project -- respawn or redirect this work yourself."

        # BE-9273: the forward-persist + ack + commit sequence is scoped in ONE
        # narrow try/except (SQLAlchemyError -- the realistic failure mode for a
        # DB write: lock timeout, constraint violation, connection loss). Before
        # this fix nothing here caught a failure at all -- it propagated
        # uncaught past every caller until it hit the API-boundary's generic
        # ``except Exception`` (_comm_tools.py / comm_threads.py), which logs a
        # non-specific warning and returns the ORIGINAL post_to_thread result
        # untouched: no ``forward_notice`` field, because the exception fired
        # before that field was ever set. The sender sees a normal "success"
        # response for a message that was, in fact, never delivered to anyone
        # and whose dead-recipient cursor was never resolved -- a silent
        # dead-letter. Catching it HERE, narrowly, lets a DB failure flow
        # through the exact same sender-facing notice channel every other
        # "could not forward" branch in this method already uses, so the
        # boundary's generic catch is never the only thing standing between a
        # failed redirect and total silence.
        try:
            forwarded = await forward_action_required_to_orchestrator(
                session,
                tenant_key=tenant_key,
                project_id=project_id,
                thread_id=message.thread_id,
                dead_agent_id=dead_execution.agent_id,
                dead_agent_label=dead_label,
                terminal_status=dead_execution.status,
                original_content=message.content,
                original_from_display_name=message.from_display_name or message.from_agent_id or "unknown",
            )
            if forwarded is None:
                # Should be rare (the orchestrator resolved live moments earlier), but
                # never silently drop the dead cursor if it happens.
                logger.warning(
                    "BE-9247: forward_action_required_to_orchestrator returned None for message %s "
                    "(dead recipient %s, project %s) despite a live orchestrator resolving moments "
                    "earlier -- leaving cursor unresolved",
                    message.id,
                    sanitize(dead_execution.agent_id),
                    project_id,
                )
                return f"{finished_prefix} and the redirect to the live orchestrator failed; the message was not forwarded."

            await thread_repo.ack_messages_for_participant(
                session, tenant_key, agent_id=dead_execution.agent_id, message_ids=[message.id]
            )
            await session.commit()
        except SQLAlchemyError:
            # Narrow, structured, and never silent: message id + destination
            # (both the dead original recipient AND the orchestrator the forward
            # was addressed to) are always in the log line, so a failure here is
            # traceable to the exact message and the exact intended destination.
            logger.exception(
                "BE-9273: forward-on-send redirect raised persisting/committing the "
                "forwarded message for message %s (dead recipient %s, destination "
                "orchestrator %s, project %s) -- the original message was NOT forwarded "
                "and its cursor is left un-acked",
                message.id,
                sanitize(dead_execution.agent_id),
                sanitize(live_orchestrator.agent_id),
                project_id,
            )
            # The failed flush/commit above leaves the session's transaction
            # aborted -- roll back explicitly so callers (the auto-block loop
            # over other recipients, then the owning session's own commit-on-
            # exit) don't inherit a poisoned transaction and raise a SECOND,
            # unrelated error that would bury this one.
            try:
                await session.rollback()
            except SQLAlchemyError:
                logger.exception(
                    "BE-9273: rollback after failed forward-on-send also raised for message %s", message.id
                )
            return (
                f"{finished_prefix} and the redirect to the live orchestrator raised an error "
                "while saving the forward; the message was not forwarded."
            )

        return (
            f"{dead_label} was {dead_execution.status} -- your message was forwarded to "
            f"{live_orchestrator.agent_display_name} ({live_orchestrator.agent_id})."
        )

    async def auto_block_for_thread_post(
        self,
        *,
        message_id: str,
        to_participant: str | None,
        sender_display_name: str,
        requires_action: bool,
        tenant_key: str | None = None,
    ) -> AutoBlockOutcome:
        """Relocated reactivation coupling for Hub thread posts (BE-9012b, D5) +
        forward-on-send redirect for an already-terminal recipient (BE-9247).

        The bus's single message->lifecycle coupling
        (``send_message`` -> :meth:`_auto_block_completed_recipients`) now also fires
        on the Hub: after a ``post_to_thread`` commits, the MCP wrapper and REST
        endpoint call this so a **directed, action-required post on a project-bound
        thread** reproduces the auto-block/reactivation (BE-9012d: this is the ONLY
        remaining bus/Hub coupling — the bus itself is retired). HARD RULES (§6 rows
        7/8/16), enforced before delegating to the shared method (reused verbatim ->
        informational-never-blocks + the ``IMMUTABLE_PROJECT_STATUSES`` skip come
        free): informational (``requires_action=False``), broadcast (no explicit
        ``to_participant`` -> must never fan-reactivate every participant), and
        town-square (message carries a NULL ``project_id``) posts are all inert.

        Returns an ``AutoBlockOutcome`` (list-compatible with the auto-blocked
        agent_ids, callers doing ``blocked == [...]`` are unaffected) carrying an
        optional ``.notice`` when the recipient was already-terminal (BE-9247
        forward-on-send: the message was redirected to the live orchestrator, a
        self-forward was avoided, or no live orchestrator could be found).
        """
        # Row 8 + the broadcast guard: only a directed, action-required post can
        # reactivate a completed agent.
        if not requires_action or not to_participant:
            return AutoBlockOutcome()

        tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        if not tenant_key:
            return AutoBlockOutcome()

        async with self._get_session(tenant_key) as session:
            # BE-9247: fetch the full persisted message (not just its project_id) --
            # the forward-on-send redirect needs this SAME row's content, thread_id,
            # and original sender for the annotated repost, so one query now serves
            # what a narrower project-id-only lookup used to.
            message = await self._repo.get_message_by_id(session, tenant_key, message_id)
            # Town-square (NULL project) stays side-effect-free (HARD RULE).
            if message is None or not message.project_id:
                return AutoBlockOutcome()

            project = await self._repo.get_project(session, tenant_key, message.project_id)
            if not project:
                return AutoBlockOutcome()

            # Reuse the bus auto-block VERBATIM: a single directed recipient, never a
            # broadcast fan-out. Row 16 (IMMUTABLE_PROJECT_STATUSES skip) and row 8
            # (requires_action guard) are enforced inside the shared method. Forward the
            # already-validated ``requires_action`` (guaranteed True by the guard above)
            # rather than a literal, so this delegation is not mistaken for an
            # informational emitter passing requires_action=True (0435d AST audit).
            return await self._auto_block_completed_recipients(
                session,
                [to_participant],
                project,
                sender_display_name,
                is_broadcast_fanout=False,
                requires_action=requires_action,
                message=message,
            )
