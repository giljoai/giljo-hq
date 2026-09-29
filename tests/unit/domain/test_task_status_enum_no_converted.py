# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.domain.task_status import TASK_STATUS_META, TaskStatus


def test_converted_not_in_enum_values() -> None:
    assert "converted" not in [s.value for s in TaskStatus]


def test_converted_not_in_status_meta() -> None:
    assert all(member.value != "converted" for member in TASK_STATUS_META)


def test_enum_has_exactly_six_members() -> None:
    assert {s.name for s in TaskStatus} == {
        "PENDING",
        "IN_PROGRESS",
        "ON_HOLD",
        "COMPLETED",
        "BLOCKED",
        "CANCELLED",
    }
    assert len(list(TaskStatus)) == 6
