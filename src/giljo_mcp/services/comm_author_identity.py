# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Who wrote a Hub post, and making sure they are in the directory (BE-9289a).

Cohesive unit extracted from ``CommThreadService.post_to_thread`` to keep that module
within its size budget. It answers one question completely — *who is this author, and
is the thread's participant directory aware of them?* — because the two are inseparable:
the same three branches that decide the author's KIND also decide the name and the row.

Edition Scope: CE.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.harness_resolver import GENERIC_HARNESS


# TSK-0008: an omitted from_agent falls back to the authenticated principal. The backend
# cannot tell an agent that forgot the field from a genuine user post, so it attributes
# AND advises rather than silently stamping.
_PRINCIPAL_FALLBACK_WARNING = (
    "from_agent omitted; attributed to the authenticated principal. An AGENT post "
    "must pass from_agent (its role/lane id) or it is mis-attributed (TSK-0008)."
)
_NO_PRINCIPAL_WARNING = "from_agent omitted and no principal resolved; attributed to 'orchestrator'."

# BE-9292a: the label-shaped identity that made an undeliverable baton available to
# pass in the first place.
_LABEL_COLLISION_WARNING = (
    "from_agent '{label}' is not a registered id on this thread — '{registered}' is registered under "
    "that display name. Post and hand the baton under the registered ID: get_my_turn matches the id, "
    "so a hand-off addressed to the label reaches nobody."
)


def registered_id_for_label(participants, label: str | None) -> str | None:
    """The participant_id registered under display name ``label``, if one is.

    THE detection this incident class turns on, kept pure and shared: "is this string a
    display NAME held by a DIFFERENT registered id?" A string that IS its own holder's
    id is no collision (``participant_id != label``) — that is the ordinary case where
    an agent's name and id are the same, and treating it as ambiguous would refuse
    every normal hand-off.

    BE-9292a-F1: the answer is needed in two places with opposite consequences. For a
    post's AUTHOR it is advice (``comm_author_identity``) — the author reaches whoever
    it likes and only mis-attributes itself. For a post's ADDRESSEE and BATON TARGET
    (``comm_baton_targets``) it is a refusal, because those are the two strings that
    decide where a message and a turn get DELIVERED, and a label there routes both to
    an identity nobody polls under.
    """
    if not label:
        return None
    for participant in participants:
        if participant.display_name == label and participant.participant_id != label:
            return participant.participant_id
    return None


async def _label_collision_warning(repo, session, tenant_key, thread_id, from_agent) -> str | None:
    """Warn when ``from_agent`` is a display LABEL already held by a registered id.

    The shape of the 2026-07-25 incident: a conductor registered under a UUID posted
    under its friendly label, the label was minted as a second identity beside it, and
    the hand-off addressed to that label could never reach the UUID the conductor was
    actually polling under. Nothing errored. This names the id that works.

    IT WARNS AND DOES NOT REWRITE. Substituting the registered id for the declared slug
    is precisely what the BE-9037 identity contract forbids — ``from_agent_id`` is the
    functional key behind recipient self-exclusion, baton matching and read cursors,
    and silently swapping it is how agent posts once rendered as the human operator. An
    unknown-but-sane slug is legitimate (ad-hoc lane ids are real), so it cannot be a
    rejection either. Only called when the author holds no row yet, so the directory
    read costs nothing on the common path.
    """
    registered = registered_id_for_label(
        await repo.get_participants(session, tenant_key, thread_id),
        from_agent,
    )
    return _LABEL_COLLISION_WARNING.format(label=from_agent, registered=registered) if registered else None


@dataclass(frozen=True)
class AuthorIdentity:
    """The server's answer for one post's author.

    ``kind`` doubles as the participant_type ('agent' | 'user') — the two vocabularies
    are deliberately the same, so a poster's row and their messages can never disagree.
    """

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
) -> AuthorIdentity:
    """Resolve the author, then guarantee they hold a participant row on this thread.

    THE KIND IS RECORDED, NOT INFERRED. These three branches are the only place the
    server knows whether a post came from an agent or the human operator; downstream
    readers must never re-derive it from the shape of ``from_agent_id``, which is a
    self-declared functional key (recipient self-exclusion, baton matching, read
    cursors). An agent posting under a UUID slug is legitimate, and guessing from that
    shape is what once rendered agents as the human user.

    REGISTRATION IS UNCONDITIONAL. It used to happen only inside the broadcast branch
    and only when the thread was project-anchored, so a direct message registered
    nobody and a standalone or chain thread registered no one at all — leaving the
    poster with no row and the UI with nothing authoritative to resolve against.
    ``display_name`` is never NULL here (it falls back to the slug), so the directory
    always has something to render, and the upsert lets a later explicit ``join_thread``
    replace it with a real name.
    """
    if from_agent:
        # Prefer the STORED display name from the poster's own row (set at join_thread)
        # so every reader sees the friendly role; no row, or no name, falls back to the
        # slug — never a crash, never worse than pre-fix.
        participant = await repo.get_participant(session, tenant_key, thread_id, from_agent)
        identity = AuthorIdentity(
            agent_id=from_agent,
            kind="agent",
            display_name=(participant.display_name if participant else None) or from_agent,
            # BE-9292a: an author with no row of its own may be a display label
            # shadowing a registered id — say so rather than mint a silent twin.
            warning=(
                None
                if participant
                else await _label_collision_warning(repo, session, tenant_key, thread_id, from_agent)
            ),
        )
    elif user_id:
        user = await user_repo.get_user_by_id(session, user_id, tenant_key)
        identity = AuthorIdentity(
            agent_id=user_id,
            kind="user",
            display_name=user.display_name if user else "user",
            warning=_PRINCIPAL_FALLBACK_WARNING,
        )
    else:
        identity = AuthorIdentity(
            agent_id="orchestrator",
            kind="agent",
            display_name="orchestrator",
            warning=_NO_PRINCIPAL_WARNING,
        )

    await repo.add_participant(
        session,
        tenant_key,
        thread_id,
        participant_id=identity.agent_id,
        participant_type=identity.kind,
        display_name=identity.display_name,
        harness=detected_harness or GENERIC_HARNESS,
        touch_last_seen=True,  # posting is activity
    )
    return identity
