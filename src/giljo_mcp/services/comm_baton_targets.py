# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Who can be handed the baton, and who belongs in the directory (BE-9292a).

The reader-side and baton-side half of the invariant ``comm_author_identity``
(BE-9289a) established for the writer: *the participant registry is the authority
for who can acknowledge a post and who can be handed the baton.* That module
answers "who wrote this, and does the directory know them"; this one answers "can
this identity actually be reached, and if we are delivering to it, why is it not
in the directory".

Extracted rather than inlined for the reason the BE-9289a seam was: it keeps
``comm_thread_service`` under the 800-line CI guardrail, and reachability is one
idea with three callers — the atomic post-with-baton hand-off, the standalone
``pass_baton``, and the enrolment of a directed post's addressee.

Edition Scope: CE.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.comm import CommParticipant
from giljo_mcp.services.comm_author_identity import registered_id_for_label


# The two baton values that name nobody in particular: 'all' opens the turn to any
# participant (``get_my_turn`` matches the literal), 'none' means no hand-off. Neither
# can be undeliverable, so neither is validated.
RESERVED_BATON_TARGETS = frozenset({"all", "none"})

BATON_TARGET_NOT_A_PARTICIPANT = "BATON_TARGET_NOT_A_PARTICIPANT"
TARGET_IS_A_DISPLAY_NAME = "TARGET_IS_A_DISPLAY_NAME"


def _display_name_rejection(
    participants,
    thread_id: str,
    field: str,
    target: str | None,
    current_owner: str | None,
) -> dict[str, Any] | None:
    """The refusal when ``target`` is a display NAME held by a different registered id.

    BE-9292a-F1 — the check that closes the incident on the path it actually travels.
    The first pass validated ``pass_baton_to`` but exempted ``to_participant`` as an
    identity the post itself enrols. That exemption is right for a genuine first-contact
    addressee and wrong for a label, and because the BE-9197 auto-pass sets
    ``pass_baton_to := to_participant``, it excused the DEFAULT hand-off from the very
    check written for it. Both fields are screened here, so neither can launder a label.

    IT OUTRANKS REGISTRATION, deliberately. A label addressed once used to be MINTED as
    a participant row, and that row then satisfied the registry check — so the
    validator's own allowlist was populated by unvalidated input and the guard decayed
    with every mistyped addressee. Refusing a shadowed label whether or not something
    already minted it is what stops that decay, and it heals threads already carrying a
    phantom row without a migration (tolerance over data surgery).

    NARROW BY DESIGN. Only a genuine collision is refused. An unknown-but-sane addressee
    is a legitimate, common, previously working first-contact post — refusing those
    wholesale would be a worse regression than the defect. A plain unknown string has no
    registered agent hiding behind it; a shadowed label does, which is what strands.
    """
    registered_id = registered_id_for_label(participants, target)
    if registered_id is None:
        return None
    # The string can be BOTH a display name here and an id in its own right — either a
    # legacy phantom row minted before this check existed, or a genuine id that happens
    # to match someone's display name. The two are indistinguishable from the columns
    # (a row's authority is settled by its writer, not recorded), so this refuses either
    # way rather than guessing which identity the sender meant: ambiguous delivery is
    # exactly how the original hand-off was lost. The hint must not claim it is "not an
    # id" when it is one, so say what is actually true and let the caller disambiguate.
    also_an_id = any(p.participant_id == target for p in participants)
    if also_an_id:
        # BE-9292a-F2 — this case gets its own remedy, because the shared one was wrong
        # here. ``registered_id`` is the SHADOWER: the participant that took the target
        # string as its display name. The agent the caller meant is almost certainly the
        # one polling under the string itself, so telling them to "use registered_id"
        # hands the baton to the wrong agent and the intended recipient still never
        # wakes — the exact harm this refusal exists to prevent, delivered through its
        # own remedy text. Neither id is a safe substitute, so name none of them as the
        # answer and give the only remedy there is: clear the collision.
        #
        # THAT REMEDY IS DOCUMENTED NOWHERE ELSE, which is why it is spelled out in the
        # payload. ``join_thread`` is the sole authoritative writer of ``display_name``
        # (the only ``authoritative=True`` call site) — there is no REST route and no
        # operator rename — so a shadow is cleared by having the shadower re-join under
        # a different name. A blank does not clear it either: a non-authoritative write
        # fills blanks and never corrects.
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
        # UNCHANGED — nothing moved. Same contract as the rejection below.
        "next_action_owner": current_owner,
        "valid_participants": sorted(p.participant_id for p in participants),
        "hint": hint,
    }


async def _is_tenant_user(user_repo, session: AsyncSession, tenant_key: str, identity: str) -> bool:
    """Whether this identity is a real human user of the tenant.

    ``users.id`` is a String column, so an arbitrary agent slug is a plain miss here
    and never a cast error that would poison the caller's transaction.
    """
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
    """Map the literal ``"user"`` to the tenant operator's real id (BE-9365b).

    A user id has always been a legal target — ``_is_tenant_user`` below resolves one,
    and the baton has accepted one since it existed. The gap was never capability, it
    was DISCOVERABILITY: an agent has no way to learn the operator's uuid. So when an
    agent needed a decision only the human could make, it had exactly one move it knew
    about — broadcast "waiting for you" into the room and hope. That is why the Hub is
    full of prose asking for the operator's attention while ``next_action_owner`` points
    at nobody, and it is why the card's honesty rule (yellow ONLY from the baton, never
    from the words in a post) currently has nothing to fire on.

    ``"user"`` is a name an agent can guess without being told. That is the entire point.

    Safe as a reserved word because ``users.id`` is a uuid: no real user can be called
    "user", so this can never shadow a legitimate id.

    Resolution is unambiguous by construction. ``tenant_key`` is per-USER and 1:1
    permanently (ADR-009 — Teams is cancelled, there is no future per-org flip), so a
    tenant has exactly one human. If that ever stops being true this returns ``None``
    rather than guessing which human was meant, and the caller's existing rejection path
    reports it — a wrong human is worse than a refusal.
    """
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
    """Put someone we are delivering to into the thread's directory.

    DELIVERY IS ENROLMENT. Two registries used to answer "is this agent in this
    conversation": ``message_recipients`` (who a post was delivered to) and
    ``comm_participants`` (who joined). Only the second gates ``mark_read``, and only
    the first fed the unread badge and the closeout gate — so a directed post could
    oblige an agent to reply to something it was structurally unable to acknowledge.
    Registering the addressee at the moment of delivery is what makes the two unable
    to disagree; it is the same write-boundary guarantee BE-9289a gave the writer.

    The registration is deliberately NON-authoritative (the ``add_participant``
    default): it fills blanks and never corrects, so a later ``join_thread`` still
    replaces the placeholder with the agent's declared name and role.

    ``participant_type`` is settled here and only here, because the upsert INSERTs it
    and never revises it — a human addressed by an agent and stamped 'agent' would
    render as an agent in the Hub directory permanently, which is exactly the class of
    mis-attribution BE-9289a's recorded-not-inferred kind exists to prevent.
    """
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
    """``None`` when the baton can actually reach ``target``; else the refusal.

    The hand-off used to be written straight through, and the post still answered
    ``baton_passed: true`` — so a mistyped id, or a display LABEL passed where an id
    belongs, set ``next_action_owner`` to something no ``get_my_turn`` could ever
    match. There was no error, no log line, and no symptom except a conductor that
    never woke and a chain that went quiet. Observed live on 2026-07-25.

    Failing loudly is the safe direction here: a baton that cannot be delivered is
    already broken, and the refusal can name the ids that would have worked, which a
    silent success never could.

    ``also_reachable`` carries the identities the CALLING post itself registers (its
    author, its addressee). Without them a first-contact directed post — the BE-9197
    auto-pass, the single most common hand-off there is — would be refused for handing
    the baton to the very agent it is enrolling.

    A human user is reachable whether or not they ever spoke on this thread: the
    operator's my-turn view is per-user, not per-participation, so an agent handing
    the baton back to the person must keep working.

    Returns the BE-6081 domain-rejection shape (a declined request delivered as normal
    tool content, not an error), matching ``NOT_A_PARTICIPANT``. It reports
    ``next_action_owner`` — UNCHANGED, because nothing moved — so a caller that patches
    its view from this response lands on the truth instead of blanking the baton it
    still holds.
    """
    if not target or target in RESERVED_BATON_TARGETS:
        return None

    if participants is None:
        participants = await repo.get_participants(session, tenant_key, thread_id)

    # BE-9292a-F1: a shadowed label is refused BEFORE the reachability exemptions,
    # because both of them — registration and also_reachable — are exactly what a
    # minted or self-enrolled label satisfies.
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
    """``None`` when a post's addressee AND its baton target can both be reached.

    One entry point for the two strings that decide delivery, sharing a single directory
    read, called before any write so a refused post persists neither message nor baton.

    THE ADDRESSEE IS SCREENED TOO, and that is the BE-9292a-F1 fix. It is checked even
    when no baton moves, because ``enrol_addressee`` registers whoever a post is
    delivered to: an unscreened label was minted as a participant and then satisfied the
    baton validator's own allowlist on the NEXT call. Screening delivery is what keeps
    the allowlist from being populated by unvalidated input.

    The addressee is checked first because it is the string the caller actually typed —
    under the auto-pass the baton merely follows it, so naming ``to_participant`` in the
    refusal points at the mistake rather than at its consequence.
    """
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
        # Mirrors resolve_and_register_author's precedence: this post registers its
        # author under exactly this id, and enrols its addressee, so both are reachable.
        also_reachable=(author_id, to_participant),
        current_owner=current_owner,
        participants=participants,
    )
