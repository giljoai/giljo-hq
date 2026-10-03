# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.agent_wake_registry import MAX_WAITERS_PER_TENANT, get_wake_registry
from giljo_mcp.services.silence_detector import DEFAULT_SILENCE_THRESHOLD_MINUTES


DEFAULT_WAIT_SECONDS = 45
MAX_WAIT_SECONDS = 55
MIN_WAIT_SECONDS = 1

TIMEOUT_ADVICE = (
    "Nothing landed. Call get_my_turn(agent_id, wait_seconds=45) again to keep holding the line -- "
    "without wait_seconds it answers immediately and you are polling, not parked. Stop only on "
    "an explicit dismissal addressed to you, or when your own post is logically the "
    "final word on every thread you are part of."
)

POST_ADVICE = (
    "Expect a response: park on get_my_turn(your agent_id, wait_seconds=45) to catch it -- "
    "without wait_seconds it returns at once and you are polling. Unless this post is a "
    "dismissal or logically the final word. If this hand-off leaves you nothing else to do, "
    'set_agent_status(status="idle") so the board shows Monitoring; report_progress wakes you.'
)

LIVENESS_QUIET_AFTER_MINUTES = DEFAULT_SILENCE_THRESHOLD_MINUTES
LIVENESS_GONE_AFTER_MINUTES = DEFAULT_SILENCE_THRESHOLD_MINUTES * 3

LIVENESS_ACTIVE = "active"
LIVENESS_QUIET = "quiet"
LIVENESS_GONE = "gone"
LIVENESS_UNKNOWN = "unknown"


class CommThreadWakeMixin:


    @staticmethod
    def _wake_targets(
        *,
        to_participant: str | None,
        requires_action: bool,
        baton_to: str | None,
        participant_ids: list[str],
    ) -> list[str]:
        targets: set[str] = set()
        if to_participant and requires_action:
            targets.add(to_participant)
        if baton_to and baton_to != "none":
            targets.update(participant_ids if baton_to == "all" else [baton_to])
        return sorted(targets)

    def _signal_wake(self, tenant_key: str, agent_ids: list[str]) -> None:
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
    def _post_advice_entry(
        set_status: str | None,
        *,
        content: str = "",
        requires_action: bool = False,
        baton_passed: bool = False,
    ) -> dict[str, str]:
        if set_status in ("resolved", "closed"):
            return {}
        expects_reply = baton_passed or requires_action or content.rstrip().endswith("?")
        return {"advice": POST_ADVICE} if expects_reply else {}


    async def await_my_turn(
        self,
        *,
        agent_id: str,
        timeout_seconds: int | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        tk = self._resolve_tenant(tenant_key)
        if not agent_id:
            raise ValidationError("agent_id is required", context={"operation": "comm_thread.await_my_turn"})
        timeout = self._resolve_wait_seconds(timeout_seconds)

        registry = get_wake_registry()
        if registry.waiter_count(tk) >= MAX_WAITERS_PER_TENANT:
            empty = {"agent_id": agent_id, "count": 0, "threads": [], "directed_action": [], "loop_directives": []}
            return {**empty, "woken": False, "wake_reason": "waiter_limit", "waited_seconds": 0}

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
            fresh = await self.get_my_turn(agent_id=agent_id, tenant_key=tk)
            return {**fresh, "woken": True, "wake_reason": "signalled", "waited_seconds": waited}
        finally:
            registry.unregister(tk, agent_id, event)

    @staticmethod
    def _resolve_wait_seconds(timeout_seconds: int | None) -> int:
        if not timeout_seconds:
            return DEFAULT_WAIT_SECONDS
        return max(MIN_WAIT_SECONDS, min(int(timeout_seconds), MAX_WAIT_SECONDS))


    async def get_participant_liveness(self, *, thread_id: str, tenant_key: str | None = None) -> dict[str, Any]:
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
            "thresholds": {
                "quiet_after_minutes": LIVENESS_QUIET_AFTER_MINUTES,
                "gone_after_minutes": LIVENESS_GONE_AFTER_MINUTES,
            },
        }

    @staticmethod
    def _liveness_state(last_seen_at: str | None, now: datetime) -> tuple[str, int | None]:
        if not last_seen_at:
            return LIVENESS_UNKNOWN, None
        try:
            seen = datetime.fromisoformat(last_seen_at)
        except (TypeError, ValueError):
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
        agent_id = turn.get("agent_id")
        holds_baton = bool(agent_id) and any(t.get("next_action_owner") == agent_id for t in turn.get("threads") or [])
        return holds_baton or bool(turn.get("directed_action"))
