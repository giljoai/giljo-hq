# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import CodedRefusalError
from giljo_mcp.models.comm import CommParticipant
from giljo_mcp.services.comm_author_identity import registered_id_for_label


RESERVED_BATON_TARGETS = frozenset({"all", "none"})

BATON_TARGET_NOT_A_PARTICIPANT = "BATON_TARGET_NOT_A_PARTICIPANT"
TARGET_IS_A_DISPLAY_NAME = "TARGET_IS_A_DISPLAY_NAME"


class HubTargetRefusedError(CodedRefusalError):

    default_status_code = 409

    def __init__(self, refusal: dict[str, Any]):
        super().__init__(refusal["hint"], error_code=refusal["error"], context=refusal)
        self.code = refusal["error"]
        self.refusal = refusal

    def as_refusal(self) -> dict[str, Any]:
        return dict(self.refusal)


def _display_name_rejection(
    participants,
    thread_id: str,
    field: str,
    target: str | None,
    current_owner: str | None,
) -> dict[str, Any] | None:
    registered_id = registered_id_for_label(participants, target)
    if registered_id is None:
        return None
    also_an_id = any(p.participant_id == target for p in participants)
    if also_an_id:
        hint = (
            f"'{target}' is registered as an id AND is the display name of '{registered_id}', so a hand-off "
            f"to it is ambiguous. Both identities are live, so neither is a safe substitute for the other and "
            f"retrying with '{registered_id}' would hand the turn to the participant SHADOWING the name rather "
            f"than the one polling under it. Clear the collision instead: join_thread is the only writer that "
            f"can set a display name, so have '{registered_id}' re-join this thread under a display name that "
            f"is not another participant's id, then retry {field}='{target}'."
        )
    else:
        hint = (
            f"'{target}' is a display NAME on this thread, not an id — '{registered_id}' is registered under "
            f"it. Name the participant you mean explicitly as {field} — '{registered_id}' is the id the agent "
            "behind that display name polls under. get_my_turn and message delivery both match the id, so "
            "addressing a display name reaches an identity nobody polls under and the hand-off is lost silently."
        )
    return {
        "success": False,
        "error": TARGET_IS_A_DISPLAY_NAME,
        "thread_id": thread_id,
        "field": field,
        "requested": target,
        "registered_id": registered_id,
        "next_action_owner": current_owner,
        "valid_participants": sorted(p.participant_id for p in participants),
        "hint": hint,
    }


async def _is_tenant_user(user_repo, session: AsyncSession, tenant_key: str, identity: str) -> bool:
    if not identity:
        return False
    return await user_repo.get_user_by_id(session, identity, tenant_key) is not None


OPERATOR_ALIAS = "user"


async def resolve_operator_alias(
    user_repo,
    session: AsyncSession,
    tenant_key: str,
    target: str | None,
) -> str | None:
    if target != OPERATOR_ALIAS:
        return target
    users = await user_repo.list_users(session, tenant_key)
    if len(users) != 1:
        return None
    return users[0].id


async def enrol_addressee(
    repo,
    user_repo,
    session: AsyncSession,
    tenant_key: str,
    thread_id: str,
    participant_id: str,
    *,
    touch_last_seen: bool = False,
) -> CommParticipant:
    kind = "user" if await _is_tenant_user(user_repo, session, tenant_key, participant_id) else "agent"
    return await repo.add_participant(
        session,
        tenant_key,
        thread_id,
        participant_id=participant_id,
        participant_type=kind,
        touch_last_seen=touch_last_seen,
    )


async def baton_target_rejection(
    repo,
    user_repo,
    session: AsyncSession,
    tenant_key: str,
    thread_id: str,
    target: str,
    *,
    also_reachable: tuple[str | None, ...] = (),
    current_owner: str | None = None,
    participants: list[CommParticipant] | None = None,
) -> dict[str, Any] | None:
    if not target or target in RESERVED_BATON_TARGETS:
        return None

    if participants is None:
        participants = await repo.get_participants(session, tenant_key, thread_id)

    shadowed = _display_name_rejection(participants, thread_id, "pass_baton_to", target, current_owner)
    if shadowed is not None:
        return shadowed

    registered = {p.participant_id for p in participants}
    if target in registered or target in {i for i in also_reachable if i}:
        return None
    if await _is_tenant_user(user_repo, session, tenant_key, target):
        return None

    return {
        "success": False,
        "error": BATON_TARGET_NOT_A_PARTICIPANT,
        "thread_id": thread_id,
        "requested": target,
        "next_action_owner": current_owner,
        "valid_participants": sorted(registered),
        "hint": (
            f"'{target}' is not registered on this thread, so get_my_turn would never surface it and "
            "the hand-off would be lost silently. Pass the baton to one of valid_participants, or to "
            "'all' (any participant may pick it up) or 'none' (nobody waiting). If the agent you mean "
            "is real but has not joined yet, have it join_thread first — a display name is not an id."
        ),
    }


async def post_target_rejection(
    repo,
    user_repo,
    session: AsyncSession,
    tenant_key: str,
    thread_id: str,
    *,
    to_participant: str | None,
    pass_baton_to: str | None,
    author_id: str | None,
    current_owner: str | None,
) -> dict[str, Any] | None:
    if not to_participant and not pass_baton_to:
        return None

    participants = await repo.get_participants(session, tenant_key, thread_id)
    shadowed = _display_name_rejection(participants, thread_id, "to_participant", to_participant, current_owner)
    if shadowed is not None:
        return shadowed
    if not pass_baton_to:
        return None

    return await baton_target_rejection(
        repo,
        user_repo,
        session,
        tenant_key,
        thread_id,
        pass_baton_to,
        also_reachable=(author_id, to_participant),
        current_owner=current_owner,
        participants=participants,
    )


def broadcast_reply_should_clear_baton(
    clear_baton_on_broadcast_reply: bool,
    to_participant: str | None,
    current_owner: str | None,
    user_id: str | None,
) -> bool:
    if not clear_baton_on_broadcast_reply or to_participant:
        return False
    return current_owner == "all" or (bool(user_id) and current_owner == user_id)
