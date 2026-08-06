# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9289a — unit tests for the Hub author-identity resolver.

``resolve_and_register_author`` is the single place the server decides WHAT a post's
author is ('agent' vs 'user') and guarantees they hold a participant row. The
service-level behaviour is covered against a real database in
``test_be9289a_hub_identity_foundation.py``; these are fast branch-level unit tests of
the resolver itself, with fakes standing in for the repositories, so each of the three
attribution paths and the registration contract is pinned independently of the DB.

Parallel-safe: pure in-memory fakes, no DB, no module-level mutable state.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from giljo_mcp.harness_resolver import GENERIC_HARNESS
from giljo_mcp.services.comm_author_identity import resolve_and_register_author


pytestmark = pytest.mark.asyncio


@dataclass
class _Row:
    display_name: str | None
    # BE-9292a: the directory read that spots a display LABEL shadowing a registered
    # id needs an id on the row too. Defaulted so every existing construction stands.
    participant_id: str = ""


class _FakeRepo:
    """Records the add_participant call so the registration contract can be asserted."""

    def __init__(self, participant: _Row | None = None, directory: list[_Row] | None = None):
        self._participant = participant
        # BE-9292a: the thread's participant directory, consulted only when the author
        # holds no row of its own. Empty by default = no label collision to report.
        self._directory = directory or []
        self.registered: dict | None = None
        # BE-9292a-F1: counted so "a registered author costs no directory read" is
        # pinned by observation instead of by a warning that would be None anyway.
        self.directory_reads = 0

    async def get_participant(self, session, tenant_key, thread_id, participant_id):
        return self._participant

    async def get_participants(self, session, tenant_key, thread_id):
        self.directory_reads += 1
        return self._directory

    async def add_participant(self, session, tenant_key, thread_id, **kwargs):
        self.registered = {"tenant_key": tenant_key, "thread_id": thread_id, **kwargs}
        return _Row(kwargs.get("display_name"))


class _FakeUserRepo:
    def __init__(self, user: _Row | None = None):
        self._user = user

    async def get_user_by_id(self, session, user_id, tenant_key):
        return self._user


async def _resolve(repo, user_repo=None, **overrides):
    kwargs = {"from_agent": None, "user_id": None, "detected_harness": None, **overrides}
    return await resolve_and_register_author(repo, user_repo or _FakeUserRepo(), object(), "tk", "thread-1", **kwargs)


# --- the three attribution branches -----------------------------------------


async def test_agent_post_prefers_the_stored_display_name():
    repo = _FakeRepo(participant=_Row(display_name="Backend Implementer"))
    identity = await _resolve(repo, from_agent="agent-alpha")

    assert identity.kind == "agent"
    assert identity.agent_id == "agent-alpha"
    assert identity.display_name == "Backend Implementer"
    assert identity.warning is None


async def test_agent_post_falls_back_to_the_slug_when_unregistered():
    """A first-time poster has no row yet; the slug is a usable name, never NULL."""
    repo = _FakeRepo(participant=None)
    identity = await _resolve(repo, from_agent="lane-3-worker")

    assert identity.kind == "agent"
    assert identity.display_name == "lane-3-worker"


async def test_a_uuid_shaped_slug_is_still_an_agent():
    """The regression this project exists for: the SHAPE of the id decides nothing."""
    repo = _FakeRepo(participant=None)
    identity = await _resolve(repo, from_agent="277e2ee9-e15d-4339-9730-4ffee559cdcb")

    assert identity.kind == "agent"
    assert identity.agent_id == "277e2ee9-e15d-4339-9730-4ffee559cdcb"


async def test_principal_fallback_is_a_user_and_warns():
    repo = _FakeRepo()
    identity = await _resolve(repo, _FakeUserRepo(_Row("Operator")), user_id="user-1")

    assert identity.kind == "user"
    assert identity.agent_id == "user-1"
    assert identity.display_name == "Operator"
    assert "from_agent omitted" in identity.warning


async def test_unknown_principal_still_resolves_to_a_named_user():
    repo = _FakeRepo()
    identity = await _resolve(repo, _FakeUserRepo(None), user_id="user-ghost")

    assert identity.kind == "user"
    assert identity.display_name == "user"


async def test_no_agent_and_no_principal_attributes_to_orchestrator():
    repo = _FakeRepo()
    identity = await _resolve(repo)

    assert identity.kind == "agent"
    assert identity.agent_id == "orchestrator"
    assert identity.warning is not None


# --- the registration contract ----------------------------------------------


async def test_the_author_is_always_registered_with_a_matching_participant_type():
    """kind and participant_type share one vocabulary, so a poster's row and their
    messages can never disagree about what they are."""
    repo = _FakeRepo()
    identity = await _resolve(repo, from_agent="agent-alpha")

    assert repo.registered is not None
    assert repo.registered["participant_id"] == identity.agent_id
    assert repo.registered["participant_type"] == identity.kind == "agent"
    assert repo.registered["display_name"] == identity.display_name


async def test_a_user_post_registers_a_user_participant():
    repo = _FakeRepo()
    await _resolve(repo, _FakeUserRepo(_Row("Operator")), user_id="user-1")

    assert repo.registered["participant_type"] == "user"


async def test_posting_counts_as_activity():
    repo = _FakeRepo()
    await _resolve(repo, from_agent="agent-alpha")

    assert repo.registered["touch_last_seen"] is True


async def test_posting_registers_as_a_placeholder_writer_not_an_authoritative_one():
    """Posting says "I am here", not "my name is X" — only join_thread declares.

    If this path claimed authority it would rewrite the participant's display_name to
    the resolved fallback on every single post, so a name the agent declared via
    join_thread would be overwritten by its own slug.
    """
    repo = _FakeRepo(participant=None)
    await _resolve(repo, from_agent="agent-alpha")

    assert repo.registered.get("authoritative", False) is False


async def test_detected_harness_is_stamped_verbatim():
    repo = _FakeRepo()
    await _resolve(repo, from_agent="agent-alpha", detected_harness="claude-code")

    assert repo.registered["harness"] == "claude-code"


async def test_undetected_harness_degrades_to_the_generic_floor():
    """A REST post, the in-memory transport, or an unknown client — never a blank."""
    repo = _FakeRepo()
    await _resolve(repo, from_agent="agent-alpha", detected_harness=None)

    assert repo.registered["harness"] == GENERIC_HARNESS == "generic"


# --- BE-9292a: a display label shadowing a registered id ----------------------


async def test_label_shadowing_a_registered_id_is_reported_not_rewritten():
    """The 2026-07-25 incident shape. A conductor registered under a UUID posts
    under its friendly label; the label is minted as a second identity beside it,
    and a baton addressed to the label can never reach the id the conductor polls
    under. The author keeps its declared slug (BE-9037 keys on it) and the caller
    is told which id actually works."""
    repo = _FakeRepo(
        participant=None,
        directory=[_Row(display_name="Ledger Zero Conductor", participant_id="36eac157-uuid")],
    )

    identity = await _resolve(repo, from_agent="Ledger Zero Conductor")

    assert identity.agent_id == "Ledger Zero Conductor", "the declared slug is never rewritten"
    assert identity.warning is not None
    assert "36eac157-uuid" in identity.warning


async def test_an_unknown_slug_that_shadows_nobody_is_not_warned_about():
    """Ad-hoc lane ids are legitimate — only a genuine collision is worth a notice,
    or every first post from a new lane would carry a false alarm."""
    repo = _FakeRepo(participant=None, directory=[_Row(display_name="EM", participant_id="em")])

    identity = await _resolve(repo, from_agent="lane-brand-new")

    assert identity.warning is None


async def test_a_registered_author_costs_no_directory_read():
    """The notice fires when an identity is being minted, not on every message —
    an author that already holds a row is never re-examined.

    BE-9292a-F1: this used to assert only ``warning is None`` against an EMPTY
    directory, which stays true whether or not the short-circuit exists — it could not
    fail for the property it names. The directory now holds a row that WOULD collide,
    so dropping the short-circuit produces a warning and fails the test, and the read
    is counted directly rather than inferred.
    """
    repo = _FakeRepo(
        participant=_Row(display_name="Alpha", participant_id="agent-alpha"),
        directory=[_Row(display_name="agent-alpha", participant_id="someone-else")],
    )

    identity = await _resolve(repo, from_agent="agent-alpha")

    assert identity.warning is None
    assert repo.directory_reads == 0, "a registered author must not trigger a directory read"
