# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9292a / BE-9292a-F1 — unit tests for baton and addressee reachability.

``comm_baton_targets`` decides whether a message and a turn can actually be
DELIVERED to the string a caller named. The service-level behaviour is covered
against a real database in ``test_be9292a_participant_registry.py`` and over the wire
in ``test_be9292a_participant_registry_mcp_boundary.py``; these are fast branch-level
unit tests of the detector and the refusal builder, so the edge cases that decide
between "refuse" and "let it through" are pinned independently of the DB.

The detector is the whole fix: refuse too much and first-contact directed posts —
legitimate, common and previously working — break, which is a worse regression than
the defect. Refuse too little and a display label strands a chain silently.

Parallel-safe: pure in-memory rows, no DB, no module-level mutable state.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from giljo_mcp.services.comm_author_identity import registered_id_for_label
from giljo_mcp.services.comm_baton_targets import (
    RESERVED_BATON_TARGETS,
    TARGET_IS_A_DISPLAY_NAME,
    _display_name_rejection,
    baton_target_rejection,
    resolve_operator_alias,
)


@dataclass
class _Row:
    participant_id: str
    display_name: str | None = None


class _FakeRepo:
    """Counts directory reads so "never reached the DB" is observed, not inferred."""

    def __init__(self, rows: list[_Row]):
        self._rows = rows
        self.reads = 0

    async def get_participants(self, session, tenant_key, thread_id):
        self.reads += 1
        return self._rows


_CONDUCTOR = _Row("36eac157-uuid", "Ledger Zero Conductor")

# The sentence that is correct ONLY when the target is a plain label. Held here so the
# two hint tests below can assert its presence and its absence against the same string.
_SHARED_PLAIN_LABEL_TAIL = "is the id the agent behind that display name polls under"


# --- the detector -----------------------------------------------------------


def test_a_display_name_held_by_another_id_is_a_collision():
    """The incident shape, and the only shape that gets refused."""
    assert registered_id_for_label([_CONDUCTOR], "Ledger Zero Conductor") == "36eac157-uuid"


def test_an_id_that_is_its_own_display_name_is_not_a_collision():
    """The ordinary case — an agent whose name and id are the same string. Treating
    this as ambiguous would refuse practically every normal hand-off."""
    assert registered_id_for_label([_Row("em", "em")], "em") is None


def test_an_unknown_string_shadows_nobody():
    """A first-contact addressee has no registered agent hiding behind it, so it is
    not the shape that strands and must stay deliverable."""
    assert registered_id_for_label([_CONDUCTOR], "lane-brand-new") is None


def test_a_row_with_no_display_name_never_collides():
    """Rows enrolled by delivery carry no name; a NULL must not match a NULL target."""
    assert registered_id_for_label([_Row("uuid-1", None)], "Ledger Zero Conductor") is None
    assert registered_id_for_label([_Row("uuid-1", None)], None) is None


def test_matching_is_exact_not_case_folded():
    """Names are compared as stored. Case-folding here would refuse targets whose
    only relation to a display name is a coincidence of spelling."""
    assert registered_id_for_label([_Row("uuid-1", "conductor")], "Conductor") is None


def test_an_empty_target_is_never_a_collision():
    for empty in ("", None):
        assert registered_id_for_label([_CONDUCTOR], empty) is None


def test_an_empty_directory_cannot_collide():
    assert registered_id_for_label([], "anything") is None


# --- the refusal ------------------------------------------------------------


def test_the_refusal_names_the_id_that_would_have_worked():
    """An agent must be able to fix the hand-off from the payload alone."""
    rejection = _display_name_rejection([_CONDUCTOR], "t-1", "pass_baton_to", "Ledger Zero Conductor", "em")

    assert rejection["success"] is False
    assert rejection["error"] == TARGET_IS_A_DISPLAY_NAME
    assert rejection["registered_id"] == "36eac157-uuid"
    assert rejection["field"] == "pass_baton_to"
    assert rejection["requested"] == "Ledger Zero Conductor"
    assert "36eac157-uuid" in rejection["hint"]


def test_the_refusal_reports_the_owner_it_did_not_change():
    """Nothing moved, so a consumer patching next_action_owner from this response
    lands on the truth instead of blanking a baton the thread still holds."""
    rejection = _display_name_rejection([_CONDUCTOR], "t-1", "pass_baton_to", "Ledger Zero Conductor", "em")

    assert rejection["next_action_owner"] == "em"


def test_a_target_that_is_also_a_registered_id_is_refused_without_denying_it():
    """Ambiguous either way — a legacy phantom row or a genuine id that happens to
    match a display name, indistinguishable from the columns. It still refuses,
    because guessing which identity the sender meant is how the hand-off was lost;
    but the hint must not tell the caller the id does not exist when it does."""
    rows = [_Row("conductor", "Relay"), _Row("Relay", "Relay Coordinator")]

    rejection = _display_name_rejection(rows, "t-1", "pass_baton_to", "Relay", "em")

    assert rejection["error"] == TARGET_IS_A_DISPLAY_NAME
    assert "ambiguous" in rejection["hint"]
    assert "not an id" not in rejection["hint"]


def test_the_ambiguous_refusal_does_not_point_the_caller_at_the_shadower():
    """BE-9292a-F2 — the remedy must not reproduce the harm it exists to prevent.

    ``registered_id`` means different things in the two cases. For a plain label it is
    the INTENDED recipient, and telling the caller to use it is the fix. For a target
    that is also a registered id it is the SHADOWER — the participant that took the
    string as its display name — while the agent the caller meant is almost certainly
    the one polling under the string itself. An agent that follows a shared tail here
    hands the baton to the shadower, so the intended recipient still never wakes: the
    exact harm this project exists to prevent, delivered through the remedy text.

    So the two cases get two tails, and this pins the ambiguous one against silently
    reverting to the shared wording. Its sibling below pins the plain-label tail, which
    is what makes the pair two-sided — collapse them back into one string and whichever
    text survives fails one of these two tests.
    """
    # The replacement-lane shape: a lane joins under the display name of the lane it
    # took over, so that name is now both a live id and somebody else's label.
    rows = [_Row("relay-standin", "relay"), _Row("relay", "Relay Coordinator")]

    hint = _display_name_rejection(rows, "t-1", "pass_baton_to", "relay", "em")["hint"]

    # Both identities are live, and the refusal must say so rather than nominate one.
    assert "both identities are live" in hint.lower()
    assert _SHARED_PLAIN_LABEL_TAIL not in hint, "the ambiguous case is wearing the plain-label remedy"
    # The only remedy that exists — and it is documented nowhere else, so it must be here.
    assert "join_thread" in hint
    assert "relay-standin" in hint, "the participant that must re-join has to be named"


def test_the_plain_label_refusal_still_names_the_id_to_use():
    """The other half of the pair. A plain label has one right answer — the registered
    id — and the ambiguous case's caution must not leak over and withhold it."""
    hint = _display_name_rejection([_CONDUCTOR], "t-1", "pass_baton_to", "Ledger Zero Conductor", "em")["hint"]

    assert _SHARED_PLAIN_LABEL_TAIL in hint
    assert "36eac157-uuid" in hint


def test_a_clean_target_produces_no_refusal():
    assert _display_name_rejection([_CONDUCTOR], "t-1", "pass_baton_to", "lane-a", "em") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved", sorted(RESERVED_BATON_TARGETS))
async def test_a_reserved_target_survives_a_participant_named_after_it(reserved):
    """'all' and 'none' name nobody in particular and can never be undeliverable, so
    the reserved check has to run BEFORE the collision check. An agent joining with
    the display name 'all' would otherwise make the reserved hand-off unusable for
    the whole thread — pinned here because the ordering is the only thing preventing
    it, and nothing else would catch a future reshuffle."""
    repo = _FakeRepo([_Row("some-uuid", reserved)])

    assert await baton_target_rejection(repo, None, object(), "tk", "t-1", reserved) is None
    assert repo.reads == 0, "a reserved target must not even reach the directory"


# ---------------------------------------------------------------------------
# The "user" alias — how an agent addresses the operator (BE-9365b).
# ---------------------------------------------------------------------------


@dataclass
class _FakeUser:
    id: str


class _FakeUserRepo:
    """Only what resolve_operator_alias touches."""

    def __init__(self, users):
        self.users = users
        self.calls = 0

    async def list_users(self, session, tenant_key):  # noqa: ARG002 - signature parity
        self.calls += 1
        return self.users


@pytest.mark.asyncio
async def test_the_user_alias_resolves_to_the_tenant_operator():
    """The capability always existed; the NAME is the fix.

    A user id has been a legal baton target since the baton existed, but an agent has no
    way to discover the operator's uuid — so it broadcast "waiting for you" into the room
    instead of directing the request. 'user' is a name an agent can reach for without
    being told it.
    """
    repo = _FakeUserRepo([_FakeUser("operator-uuid")])

    assert await resolve_operator_alias(repo, object(), "tk", "user") == "operator-uuid"


@pytest.mark.asyncio
async def test_a_non_alias_target_is_returned_untouched_and_costs_no_lookup():
    """Every post and hand-off runs through this, so the common path must not pay for a
    users query it does not need."""
    repo = _FakeUserRepo([_FakeUser("operator-uuid")])

    assert await resolve_operator_alias(repo, object(), "tk", "lane-a") == "lane-a"
    assert await resolve_operator_alias(repo, object(), "tk", None) is None
    assert repo.calls == 0


@pytest.mark.asyncio
async def test_an_ambiguous_tenant_refuses_rather_than_guessing():
    """tenant_key is per-USER and 1:1 permanently (ADR-009), so this should be
    unreachable. If it ever becomes reachable, handing the baton to an arbitrarily
    chosen human is worse than refusing: the wrong person is told to act while the
    right one sees nothing. Returning None routes it into the existing rejection path,
    which names the ids that would have worked.
    """
    assert await resolve_operator_alias(_FakeUserRepo([]), object(), "tk", "user") is None
    two = _FakeUserRepo([_FakeUser("a"), _FakeUser("b")])
    assert await resolve_operator_alias(two, object(), "tk", "user") is None
