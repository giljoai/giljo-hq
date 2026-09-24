# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace

import pytest

from giljo_mcp.services.task_service._handover_guards import (
    HANDOVER_NOT_CONVERTIBLE,
    PENDING_HANDOVER_NOT_ARCHIVABLE,
    handover_not_convertible,
    handover_state,
    pending_handover_not_archivable,
)


def _task(abbreviation: str | None, status):
    return SimpleNamespace(
        task_type=SimpleNamespace(abbreviation=abbreviation) if abbreviation else None,
        status=status,
    )


async def _reader(task):
    async def _get(_task_id):
        return task

    return _get


@pytest.mark.asyncio
async def test_a_handover_is_recognised_and_its_status_reported() -> None:
    state = await handover_state(await _reader(_task("HND", "pending")), "t-1")
    assert state == (True, "pending")


@pytest.mark.asyncio
async def test_an_ordinary_task_is_not_a_handover() -> None:
    is_handover, _status = await handover_state(await _reader(_task("TSK", "pending")), "t-1")
    assert is_handover is False


@pytest.mark.asyncio
async def test_a_task_with_no_type_record_is_not_a_handover() -> None:
    is_handover, _status = await handover_state(await _reader(_task(None, "pending")), "t-1")
    assert is_handover is False


@pytest.mark.asyncio
async def test_an_enum_status_is_unwrapped_to_its_value() -> None:
    status = SimpleNamespace(value="pending")
    _is_handover, reported = await handover_state(await _reader(_task("HND", status)), "t-1")
    assert reported == "pending"


@pytest.mark.asyncio
async def test_an_unreadable_task_is_reported_as_not_a_handover() -> None:

    async def _explodes(_task_id):
        raise RuntimeError("no such task")

    assert await handover_state(_explodes, "t-1") == (False, None)


def test_the_refusals_carry_their_codes_and_name_the_task() -> None:
    convert = handover_not_convertible("t-9")
    assert convert["success"] is False
    assert convert["error"] == HANDOVER_NOT_CONVERTIBLE
    assert convert["task_id"] == "t-9"

    archive = pending_handover_not_archivable("t-9")
    assert archive["success"] is False
    assert archive["error"] == PENDING_HANDOVER_NOT_ARCHIVABLE
    assert archive["task_id"] == "t-9"


def test_both_refusals_say_nothing_was_changed() -> None:
    for rejection in (handover_not_convertible("t-9"), pending_handover_not_archivable("t-9")):
        assert "Nothing was changed" in rejection["message"]


def test_each_refusal_says_what_to_do_instead() -> None:
    assert "create_project" in handover_not_convertible("t-9")["message"]
    assert "in_progress" in pending_handover_not_archivable("t-9")["message"]
