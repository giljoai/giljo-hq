# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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

    def __init__(self, rows: list[_Row]):
        self._rows = rows
        self.reads = 0

    async def get_participants(self, session, tenant_key, thread_id):
        self.reads += 1
        return self._rows


_CONDUCTOR = _Row("36eac157-uuid", "Ledger Zero Conductor")

_SHARED_PLAIN_LABEL_TAIL = "is the id the agent behind that display name polls under"




def test_a_display_name_held_by_another_id_is_a_collision():
    assert registered_id_for_label([_CONDUCTOR], "Ledger Zero Conductor") == "36eac157-uuid"


def test_an_id_that_is_its_own_display_name_is_not_a_collision():
    assert registered_id_for_label([_Row("em", "em")], "em") is None


def test_an_unknown_string_shadows_nobody():
    assert registered_id_for_label([_CONDUCTOR], "lane-brand-new") is None


def test_a_row_with_no_display_name_never_collides():
    assert registered_id_for_label([_Row("uuid-1", None)], "Ledger Zero Conductor") is None
    assert registered_id_for_label([_Row("uuid-1", None)], None) is None


def test_matching_is_exact_not_case_folded():
    assert registered_id_for_label([_Row("uuid-1", "conductor")], "Conductor") is None


def test_an_empty_target_is_never_a_collision():
    for empty in ("", None):
        assert registered_id_for_label([_CONDUCTOR], empty) is None


def test_an_empty_directory_cannot_collide():
    assert registered_id_for_label([], "anything") is None




def test_the_refusal_names_the_id_that_would_have_worked():
    rejection = _display_name_rejection([_CONDUCTOR], "t-1", "pass_baton_to", "Ledger Zero Conductor", "em")

    assert rejection["success"] is False
    assert rejection["error"] == TARGET_IS_A_DISPLAY_NAME
    assert rejection["registered_id"] == "36eac157-uuid"
    assert rejection["field"] == "pass_baton_to"
    assert rejection["requested"] == "Ledger Zero Conductor"
    assert "36eac157-uuid" in rejection["hint"]


def test_the_refusal_reports_the_owner_it_did_not_change():
    rejection = _display_name_rejection([_CONDUCTOR], "t-1", "pass_baton_to", "Ledger Zero Conductor", "em")

    assert rejection["next_action_owner"] == "em"


def test_a_target_that_is_also_a_registered_id_is_refused_without_denying_it():
    rows = [_Row("conductor", "Relay"), _Row("Relay", "Relay Coordinator")]

    rejection = _display_name_rejection(rows, "t-1", "pass_baton_to", "Relay", "em")

    assert rejection["error"] == TARGET_IS_A_DISPLAY_NAME
    assert "ambiguous" in rejection["hint"]
    assert "not an id" not in rejection["hint"]


def test_the_ambiguous_refusal_does_not_point_the_caller_at_the_shadower():
    rows = [_Row("relay-standin", "relay"), _Row("relay", "Relay Coordinator")]

    hint = _display_name_rejection(rows, "t-1", "pass_baton_to", "relay", "em")["hint"]

    assert "both identities are live" in hint.lower()
    assert _SHARED_PLAIN_LABEL_TAIL not in hint, "the ambiguous case is wearing the plain-label remedy"
    assert "join_thread" in hint
    assert "relay-standin" in hint, "the participant that must re-join has to be named"


def test_the_plain_label_refusal_still_names_the_id_to_use():
    hint = _display_name_rejection([_CONDUCTOR], "t-1", "pass_baton_to", "Ledger Zero Conductor", "em")["hint"]

    assert _SHARED_PLAIN_LABEL_TAIL in hint
    assert "36eac157-uuid" in hint


def test_a_clean_target_produces_no_refusal():
    assert _display_name_rejection([_CONDUCTOR], "t-1", "pass_baton_to", "lane-a", "em") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved", sorted(RESERVED_BATON_TARGETS))
async def test_a_reserved_target_survives_a_participant_named_after_it(reserved):
    repo = _FakeRepo([_Row("some-uuid", reserved)])

    assert await baton_target_rejection(repo, None, object(), "tk", "t-1", reserved) is None
    assert repo.reads == 0, "a reserved target must not even reach the directory"




@dataclass
class _FakeUser:
    id: str


class _FakeUserRepo:

    def __init__(self, users):
        self.users = users
        self.calls = 0

    async def list_users(self, session, tenant_key):  # noqa: ARG002 - signature parity
        self.calls += 1
        return self.users


@pytest.mark.asyncio
async def test_the_user_alias_resolves_to_the_tenant_operator():
    repo = _FakeUserRepo([_FakeUser("operator-uuid")])

    assert await resolve_operator_alias(repo, object(), "tk", "user") == "operator-uuid"


@pytest.mark.asyncio
async def test_a_non_alias_target_is_returned_untouched_and_costs_no_lookup():
    repo = _FakeUserRepo([_FakeUser("operator-uuid")])

    assert await resolve_operator_alias(repo, object(), "tk", "lane-a") == "lane-a"
    assert await resolve_operator_alias(repo, object(), "tk", None) is None
    assert repo.calls == 0


@pytest.mark.asyncio
async def test_an_ambiguous_tenant_refuses_rather_than_guessing():
    assert await resolve_operator_alias(_FakeUserRepo([]), object(), "tk", "user") is None
    two = _FakeUserRepo([_FakeUser("a"), _FakeUser("b")])
    assert await resolve_operator_alias(two, object(), "tk", "user") is None
