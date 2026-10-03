# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from dataclasses import dataclass

import pytest

from giljo_mcp.harness_resolver import GENERIC_HARNESS
from giljo_mcp.services.comm_author_identity import resolve_and_register_author


pytestmark = pytest.mark.asyncio


@dataclass
class _Row:
    display_name: str | None
    participant_id: str = ""


class _FakeRepo:

    def __init__(self, participant: _Row | None = None, directory: list[_Row] | None = None):
        self._participant = participant
        self._directory = directory or []
        self.registered: dict | None = None
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




async def test_agent_post_prefers_the_stored_display_name():
    repo = _FakeRepo(participant=_Row(display_name="Backend Implementer"))
    identity = await _resolve(repo, from_agent="agent-alpha")

    assert identity.kind == "agent"
    assert identity.agent_id == "agent-alpha"
    assert identity.display_name == "Backend Implementer"
    assert identity.warning is None


async def test_agent_post_falls_back_to_the_slug_when_unregistered():
    repo = _FakeRepo(participant=None)
    identity = await _resolve(repo, from_agent="lane-3-worker")

    assert identity.kind == "agent"
    assert identity.display_name == "lane-3-worker"


async def test_a_uuid_shaped_slug_is_still_an_agent():
    repo = _FakeRepo(participant=None)
    identity = await _resolve(repo, from_agent="277e2ee9-e15d-4339-9730-4ffee559cdcb")

    assert identity.kind == "agent"
    assert identity.agent_id == "277e2ee9-e15d-4339-9730-4ffee559cdcb"


async def test_be9379_bare_user_id_no_longer_attributes_to_the_user():
    from giljo_mcp.exceptions import ValidationError

    repo = _FakeRepo()
    with pytest.raises(ValidationError, match="from_agent"):
        await _resolve(repo, _FakeUserRepo(_Row("Operator")), user_id="user-1")


async def test_as_user_attributes_to_the_principal_without_advisory():
    repo = _FakeRepo()
    identity = await _resolve(repo, _FakeUserRepo(_Row("Operator")), user_id="user-1", as_user=True)

    assert identity.kind == "user"
    assert identity.agent_id == "user-1"
    assert identity.display_name == "Operator"
    assert identity.warning is None


async def test_as_user_with_unknown_principal_still_resolves_to_a_named_user():
    repo = _FakeRepo()
    identity = await _resolve(repo, _FakeUserRepo(None), user_id="user-ghost", as_user=True)

    assert identity.kind == "user"
    assert identity.display_name == "user"


async def test_as_user_without_a_principal_is_refused():
    from giljo_mcp.exceptions import ValidationError

    repo = _FakeRepo()
    with pytest.raises(ValidationError):
        await _resolve(repo, _FakeUserRepo(None), as_user=True)


async def test_no_agent_and_no_principal_is_refused():
    from giljo_mcp.exceptions import ValidationError

    repo = _FakeRepo()
    with pytest.raises(ValidationError, match="from_agent"):
        await _resolve(repo)




async def test_the_author_is_always_registered_with_a_matching_participant_type():
    repo = _FakeRepo()
    identity = await _resolve(repo, from_agent="agent-alpha")

    assert repo.registered is not None
    assert repo.registered["participant_id"] == identity.agent_id
    assert repo.registered["participant_type"] == identity.kind == "agent"
    assert repo.registered["display_name"] == identity.display_name


async def test_a_user_post_registers_a_user_participant():
    repo = _FakeRepo()
    await _resolve(repo, _FakeUserRepo(_Row("Operator")), user_id="user-1", as_user=True)

    assert repo.registered["participant_type"] == "user"


async def test_posting_counts_as_activity():
    repo = _FakeRepo()
    await _resolve(repo, from_agent="agent-alpha")

    assert repo.registered["touch_last_seen"] is True


async def test_posting_registers_as_a_placeholder_writer_not_an_authoritative_one():
    repo = _FakeRepo(participant=None)
    await _resolve(repo, from_agent="agent-alpha")

    assert repo.registered.get("authoritative", False) is False


async def test_detected_harness_is_stamped_verbatim():
    repo = _FakeRepo()
    await _resolve(repo, from_agent="agent-alpha", detected_harness="claude-code")

    assert repo.registered["harness"] == "claude-code"


async def test_undetected_harness_degrades_to_the_generic_floor():
    repo = _FakeRepo()
    await _resolve(repo, from_agent="agent-alpha", detected_harness=None)

    assert repo.registered["harness"] == GENERIC_HARNESS == "generic"




async def test_label_shadowing_a_registered_id_is_reported_not_rewritten():
    repo = _FakeRepo(
        participant=None,
        directory=[_Row(display_name="Ledger Zero Conductor", participant_id="36eac157-uuid")],
    )

    identity = await _resolve(repo, from_agent="Ledger Zero Conductor")

    assert identity.agent_id == "Ledger Zero Conductor", "the declared slug is never rewritten"
    assert identity.warning is not None
    assert "36eac157-uuid" in identity.warning


async def test_an_unknown_slug_that_shadows_nobody_is_not_warned_about():
    repo = _FakeRepo(participant=None, directory=[_Row(display_name="EM", participant_id="em")])

    identity = await _resolve(repo, from_agent="lane-brand-new")

    assert identity.warning is None


async def test_a_registered_author_costs_no_directory_read():
    repo = _FakeRepo(
        participant=_Row(display_name="Alpha", participant_id="agent-alpha"),
        directory=[_Row(display_name="agent-alpha", participant_id="someone-else")],
    )

    identity = await _resolve(repo, from_agent="agent-alpha")

    assert identity.warning is None
    assert repo.directory_reads == 0, "a registered author must not trigger a directory read"
