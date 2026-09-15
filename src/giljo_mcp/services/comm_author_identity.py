# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.harness_resolver import GENERIC_HARNESS
from giljo_mcp.utils.identity import validate_from_agent


_NO_AUTHOR_WARNING = (
    "no author declared (neither from_agent nor as_user); attributed to 'orchestrator'. "
    "An agent post must pass from_agent (its role/lane id); a post in the human user's "
    "voice must pass as_user=true (BE-9379)."
)

_LABEL_COLLISION_WARNING = (
    "from_agent '{label}' is not a registered id on this thread — '{registered}' is registered under "
    "that display name. Post and hand the baton under the registered ID: get_my_turn matches the id, "
    "so a hand-off addressed to the label reaches nobody."
)


def validate_post_author_input(from_agent: str | None, as_user: bool, max_len: int) -> str | None:
    from_agent = validate_from_agent(from_agent, max_len=max_len)
    if as_user and from_agent:
        raise ValidationError(
            "from_agent and as_user are mutually exclusive: a post is authored by an "
            "agent or by the human user, never both.",
            context={"operation": "comm_thread.post"},
        )
    return from_agent


def registered_id_for_label(participants, label: str | None) -> str | None:
    if not label:
        return None
    for participant in participants:
        if participant.display_name == label and participant.participant_id != label:
            return participant.participant_id
    return None


async def _label_collision_warning(repo, session, tenant_key, thread_id, from_agent) -> str | None:
    registered = registered_id_for_label(
        await repo.get_participants(session, tenant_key, thread_id),
        from_agent,
    )
    return _LABEL_COLLISION_WARNING.format(label=from_agent, registered=registered) if registered else None


@dataclass(frozen=True)
class AuthorIdentity:

    agent_id: str
    kind: str
    display_name: str
    warning: str | None


async def resolve_and_register_author(
    repo,
    user_repo,
    session: AsyncSession,
    tenant_key: str,
    thread_id: str,
    *,
    from_agent: str | None,
    user_id: str | None,
    detected_harness: str | None,
    as_user: bool = False,
    self_reported_status: str | None = None,
) -> AuthorIdentity:
    if from_agent:
        participant = await repo.get_participant(session, tenant_key, thread_id, from_agent)
        identity = AuthorIdentity(
            agent_id=from_agent,
            kind="agent",
            display_name=(participant.display_name if participant else None) or from_agent,
            warning=(
                None
                if participant
                else await _label_collision_warning(repo, session, tenant_key, thread_id, from_agent)
            ),
        )
    elif as_user:
        if not user_id:
            raise ValidationError(
                "as_user=true requires an authenticated user principal, and this session has none.",
                context={"operation": "comm_thread.post"},
            )
        user = await user_repo.get_user_by_id(session, user_id, tenant_key)
        identity = AuthorIdentity(
            agent_id=user_id,
            kind="user",
            display_name=user.display_name if user else "user",
            warning=None,
        )
    else:
        identity = AuthorIdentity(
            agent_id="orchestrator",
            kind="agent",
            display_name="orchestrator",
            warning=_NO_AUTHOR_WARNING,
        )

    await repo.add_participant(
        session,
        tenant_key,
        thread_id,
        participant_id=identity.agent_id,
        participant_type=identity.kind,
        display_name=identity.display_name,
        harness=detected_harness or GENERIC_HARNESS,
        touch_last_seen=True,
        self_reported_status=self_reported_status,
    )
    return identity
