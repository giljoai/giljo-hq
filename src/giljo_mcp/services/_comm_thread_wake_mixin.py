# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Coordination signals — who is waiting, and who is still alive (BE-9296a).

Two halves of one symmetric gap. Agents got no signal when work arrived for them;
orchestrators got no signal about whether an agent was still there. Both were
being papered over with prose ("poll every N minutes") and filesystem forensics.

* ``await_my_turn`` is ``get_my_turn`` without the sleep-poll cycle: zero tokens
  while parked, sub-second delivery, one call where there used to be a loop.
* ``get_participant_liveness`` reports each participant's last_seen_at plus a
  coarse derived state, so a conductor can tell "recently active" from "dark"
  without inspecting the filesystem, and a worker can tell whether its
  orchestrator is alive before deciding to hold or escalate.

Lives in its own module rather than on ``CommThreadService`` for the reason the
four sibling mixins already record: that class sits against the flat 800-line cap
with no tolerance band, so a feature landing in it has to make room rather than
shave rationale out of neighbouring code to fit.

Mixed into ``CommThreadService``, so it uses that class's tenant plumbing
(``_resolve_tenant``), its baton query (``get_my_turn``, itself mixed in from
``_comm_thread_baton_mixin``), and its participant read (``list_participants``).

Edition Scope: CE.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.agent_wake_registry import MAX_WAITERS_PER_TENANT, get_wake_registry
from giljo_mcp.services.silence_detector import DEFAULT_SILENCE_THRESHOLD_MINUTES


# How long one wake call parks before returning empty. The agent re-calls in a
# loop, so this is the re-call cadence, NOT the delivery latency — the gap
# between calls is nil, so a wake still arrives sub-second regardless.
#
# The server is never the limit (holds of 600s returned within 50ms of the
# requested wall clock, measured 2026-08-07). The limit is whatever sits IN FRONT
# of the server, and the tightest such limit is the MCP CLIENT itself: standard
# MCP client SDKs abort any request at 60s by default, and FastMCP runs
# ``json_response=True``, so nothing reaches the wire until the tool returns —
# the WHOLE wait counts against that budget with no early bytes to reset it.
#
# Measured live against production (2026-08-20, Claude Code CLI): a 57s hold
# returns normally; a 60s hold is killed by the client and surfaces as a raw
# tool ERROR ("operation timed out"). The previous DEFAULT of 60s therefore
# failed EVERY default call — agents saw a broken tool and abandoned the
# stay-on-the-line loop (project 1CZA1D). Reverse proxies/CDNs commonly cap
# around 100s, so the 60s client budget is the binding constraint.
#
# 45/55 keep a real margin under that budget. The asymmetry picks low numbers:
# a cap set too low costs one extra round trip per idle minute and is invisible;
# a cap set too high fails every wake call and presents as "the wake tool is
# broken". This is plumbing — never surface it as a user setting.
DEFAULT_WAIT_SECONDS = 45
MAX_WAIT_SECONDS = 55
MIN_WAIT_SECONDS = 1

# Returned verbatim on an idle timeout. The one moment an agent decides whether
# to keep holding the line is when a wait comes back empty, so the instruction
# rides on that payload rather than living only in protocol prose the agent may
# have scrolled past hours ago.
TIMEOUT_ADVICE = (
    "Nothing landed. Call await_my_turn again to keep holding the line. Stop only on "
    "an explicit dismissal addressed to you, or when your own post is logically the "
    "final word on every thread you are part of."
)

# Returned on every post that leaves the thread open. The Hub is a message board:
# a post usually gets a reply, and the moment the poster decides whether to walk
# away is right after posting — so the stay-available rule rides on the post's own
# response. ONE line, deliberately: this rides on every post an agent makes, and a
# paragraph here would out-shout the payload it decorates. Posts that set a
# terminal status (resolved/closed) are the conversation ENDING and do not carry it.
POST_ADVICE = (
    "Expect a response: park on await_my_turn (your agent_id) to catch it, unless this "
    "post is a dismissal or logically the final word."
)

# Liveness bands. "Quiet" deliberately REUSES the agent-silence threshold rather
# than inventing a second number: an operator who sees the Hub call a participant
# quiet while the job dashboard still calls it working would be right to distrust
# both. "Gone" is three consecutive missed check-ins at that same threshold — long
# enough that a slow-but-live agent is not written off, short enough to be useful.
#
# The per-tenant silence OVERRIDE (FE-9241) is intentionally not read here. This is
# a coarse display signal over thread participants — which include the operator and
# agents that own no job at all — so coupling every liveness read to the agent-job
# settings path would buy consistency on a different population at the cost of a
# settings round trip on a hot read.
LIVENESS_QUIET_AFTER_MINUTES = DEFAULT_SILENCE_THRESHOLD_MINUTES
LIVENESS_GONE_AFTER_MINUTES = DEFAULT_SILENCE_THRESHOLD_MINUTES * 3

LIVENESS_ACTIVE = "active"
LIVENESS_QUIET = "quiet"
LIVENESS_GONE = "gone"
LIVENESS_UNKNOWN = "unknown"


class CommThreadWakeMixin:
    """Server-side wake for a blocked agent. Mixed into CommThreadService."""

    # ------------------------------------------------------------------
    # The write side: who a write should wake
    # ------------------------------------------------------------------

    @staticmethod
    def _wake_targets(
        *,
        to_participant: str | None,
        requires_action: bool,
        baton_to: str | None,
        participant_ids: list[str],
    ) -> list[str]:
        """Resolve which agents a write should wake.

        The signal set must match EXACTLY what ``get_my_turn`` can report, or a
        wake returns "something happened" with nothing to show and the agent
        immediately re-parks — restoring the busy-poll this replaces. get_my_turn
        surfaces two things: holding the baton (including the 'all' baton), and an
        UNRESOLVED DIRECTED requires_action post. A plain broadcast is neither; it
        deliberately obligates nobody (BE-9197), so it wakes nobody.
        """
        targets: set[str] = set()
        if to_participant and requires_action:
            targets.add(to_participant)
        if baton_to and baton_to != "none":
            # The 'all' baton puts every participant's turn list in scope.
            targets.update(participant_ids if baton_to == "all" else [baton_to])
        return sorted(targets)

    def _signal_wake(self, tenant_key: str, agent_ids: list[str]) -> None:
        """Wake parked waiters. MUST be called only after the write has committed."""
        if agent_ids:
            get_wake_registry().signal(tenant_key, agent_ids)

    def _signal_post_wake(
        self,
        tenant_key: str,
        to_participant: str | None,
        requires_action: bool,
        pass_baton_to: str | None,
        baton_passed: bool,
        recipient_ids: list[str],
    ) -> None:
        """Resolve and fire the wake for a completed ``post_to_thread``.

        Both steps live here rather than at the call site so ``post_to_thread``
        stays inside the 200-line function budget, and so the ordering rule has one
        home: this MUST be called after the post's session context has exited.
        Signalling from inside it would wake a waiter that opens its own session,
        cannot see the uncommitted row, finds nothing, and re-parks — indistinguishable
        from the missed hand-off the wake exists to prevent.
        """
        self._signal_wake(
            tenant_key,
            self._wake_targets(
                to_participant=to_participant,
                requires_action=requires_action,
                baton_to=pass_baton_to if baton_passed else None,
                participant_ids=recipient_ids,
            ),
        )

    @staticmethod
    def _post_advice_entry(set_status: str | None) -> dict[str, str]:
        """The hold-the-line hint a post's response carries — see POST_ADVICE.

        Returned as a dict entry (empty when the post sets a terminal status) so
        the caller unpacks it into its result literal: the key must be ABSENT on a
        conversation-ending post, not present-but-null, and ``post_to_thread``
        sits against its 200-line budget with no room for a branch.
        """
        if set_status in ("resolved", "closed"):
            return {}
        return {"advice": POST_ADVICE}

    # ------------------------------------------------------------------
    # The read side: blocking until it is your turn
    # ------------------------------------------------------------------

    async def await_my_turn(
        self,
        *,
        agent_id: str,
        timeout_seconds: int | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Block until it is ``agent_id``'s turn, or until the wait cap expires.

        Returns the SAME payload ``get_my_turn`` returns, plus ``woken`` and
        ``wake_reason`` so a caller can tell a delivery from an idle timeout.
        ``wake_reason`` is one of:

        * ``already_pending`` — work was waiting before we parked at all
        * ``signalled`` — a message or baton landed while parked
        * ``timeout`` — nothing arrived within the cap; re-call to keep waiting
        * ``waiter_limit`` — too many parked waiters; fall back to polling

        Holds NO database session while parked. Each read acquires a session,
        reads, and releases it before the wait begins (proven under 40 concurrent
        waiters: pool ``checkedout`` stayed at 0 throughout). Holding one would
        drain the pool as waiters accumulate — the failure INF-3009f exists to
        address.
        """
        tk = self._resolve_tenant(tenant_key)
        if not agent_id:
            raise ValidationError("agent_id is required", context={"operation": "comm_thread.await_my_turn"})
        timeout = self._resolve_wait_seconds(timeout_seconds)

        registry = get_wake_registry()
        if registry.waiter_count(tk) >= MAX_WAITERS_PER_TENANT:
            # Decline to park rather than raise: this is a capacity ceiling, not
            # an error, and the caller has a working fallback.
            empty = {"agent_id": agent_id, "count": 0, "threads": [], "directed_action": [], "loop_directives": []}
            return {**empty, "woken": False, "wake_reason": "waiter_limit", "waited_seconds": 0}

        # REGISTER BEFORE READING. The reverse order loses any signal committed
        # between the read and the registration, and the waiter then blocks for
        # the full cap over work that already exists. See AgentWakeRegistry.register.
        event = registry.register(tk, agent_id)
        try:
            pending = await self.get_my_turn(agent_id=agent_id, tenant_key=tk)
            if self._has_pending_work(pending):
                return {**pending, "woken": True, "wake_reason": "already_pending", "waited_seconds": 0}

            loop = asyncio.get_running_loop()
            started = loop.time()
            try:
                await asyncio.wait_for(event.wait(), timeout)
            except TimeoutError:
                return {
                    **pending,
                    "woken": False,
                    "wake_reason": "timeout",
                    "waited_seconds": timeout,
                    "advice": TIMEOUT_ADVICE,
                }

            waited = round(loop.time() - started, 3)
            # Re-read after the wake: the signal says "something landed", it does
            # not carry what landed. The write committed before the signal fired,
            # so this read sees it.
            fresh = await self.get_my_turn(agent_id=agent_id, tenant_key=tk)
            return {**fresh, "woken": True, "wake_reason": "signalled", "waited_seconds": waited}
        finally:
            registry.unregister(tk, agent_id, event)

    @staticmethod
    def _resolve_wait_seconds(timeout_seconds: int | None) -> int:
        """Clamp a caller-supplied wait into the supported band.

        Clamped rather than rejected: the cap is plumbing an agent should not have
        to reason about, and refusing an over-long request would turn a harmless
        overshoot into a failed coordination call.
        """
        if not timeout_seconds:
            return DEFAULT_WAIT_SECONDS
        return max(MIN_WAIT_SECONDS, min(int(timeout_seconds), MAX_WAIT_SECONDS))

    # ------------------------------------------------------------------
    # Liveness: is my orchestrator still there?
    # ------------------------------------------------------------------

    async def get_participant_liveness(self, *, thread_id: str, tenant_key: str | None = None) -> dict[str, Any]:
        """Per-participant last_seen_at plus a coarse derived state.

        Reuses ``list_participants`` verbatim — the row already carries
        ``last_seen_at`` and ``harness`` (BE-9289a stamps them on every post, read
        and poll), so nothing new is written or queried. What this adds is the
        DERIVED band, which existed nowhere: a raw timestamp makes every caller
        re-invent "how stale is too stale", and they will not agree.

        Answers the question that used to cost filesystem forensics: a conductor
        reading ``gone`` knows to reassign rather than keep waiting, and a worker
        reading ``gone`` on its orchestrator knows to escalate rather than hold.
        """
        if not thread_id:
            raise ValidationError(
                "thread_id is required", context={"operation": "comm_thread.get_participant_liveness"}
            )
        tk = self._resolve_tenant(tenant_key)
        directory = await self.list_participants(thread_id=thread_id, tenant_key=tk)
        now = datetime.now(UTC)

        participants = []
        for row in directory["participants"]:
            state, age = self._liveness_state(row.get("last_seen_at"), now)
            participants.append({**row, "liveness": state, "seconds_since_seen": age})

        return {
            "thread_id": thread_id,
            "count": len(participants),
            "participants": participants,
            # Advertised so a reader never has to guess what the bands mean, and so
            # a future change to them is visible in the payload rather than silent.
            "thresholds": {
                "quiet_after_minutes": LIVENESS_QUIET_AFTER_MINUTES,
                "gone_after_minutes": LIVENESS_GONE_AFTER_MINUTES,
            },
        }

    @staticmethod
    def _liveness_state(last_seen_at: str | None, now: datetime) -> tuple[str, int | None]:
        """Band a participant's last_seen_at. Returns ``(state, seconds_since_seen)``.

        A participant that has never been seen is ``unknown``, not ``gone``: it has
        joined but not yet acted, and reporting that as "dark" would have a
        conductor reassign work from an agent that is merely starting up.
        """
        if not last_seen_at:
            return LIVENESS_UNKNOWN, None
        try:
            seen = datetime.fromisoformat(last_seen_at)
        except (TypeError, ValueError):
            # A malformed stamp is a display concern, never a reason to fail the
            # read the conductor is relying on.
            return LIVENESS_UNKNOWN, None
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=UTC)

        age_seconds = max(0, int((now - seen).total_seconds()))
        if age_seconds < LIVENESS_QUIET_AFTER_MINUTES * 60:
            return LIVENESS_ACTIVE, age_seconds
        if age_seconds < LIVENESS_GONE_AFTER_MINUTES * 60:
            return LIVENESS_QUIET, age_seconds
        return LIVENESS_GONE, age_seconds

    @staticmethod
    def _has_pending_work(turn: dict[str, Any]) -> bool:
        """Whether a get_my_turn payload represents work actually awaiting the agent.

        Both axes count: holding the baton on a thread, and an unresolved directed
        action-request that the baton has since moved past (the BE-9207 multi-lane
        clobber). ``loop_directives`` deliberately does NOT count — a standing
        cadence is not a new event, and treating it as one would make every wake
        call return instantly and restore the busy-poll this replaces.

        BE-9388: a standing ``all`` baton does not count either, for exactly the
        reason above — it is a STATE, not an event. It is set once and nothing
        clears it implicitly, so a participant of a thread left at ``all`` could
        never park again; that is the busy-poll returning through the baton axis
        instead of the directive axis. Delivery is untouched: ``pass_baton``
        signals the wake registry for every participant, so a FRESH ``all``
        hand-off still reaches a parked agent in under a second, and the thread is
        still reported on the poll surface either way.

        Keyed on the agent's own id rather than on ``count``: ``threads`` also
        carries directed-arm threads owned by third parties (BE-9207 appends
        them), so ``count`` stopped being a safe proxy for "the baton is mine".
        An owner of ``None`` can never match, since ``agent_id`` is required.
        """
        agent_id = turn.get("agent_id")
        holds_baton = bool(agent_id) and any(t.get("next_action_owner") == agent_id for t in turn.get("threads") or [])
        return holds_baton or bool(turn.get("directed_action"))
