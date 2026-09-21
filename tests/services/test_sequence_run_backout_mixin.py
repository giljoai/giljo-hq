# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ast
import inspect
import textwrap

from giljo_mcp.services.sequence_run_backout_mixin import SequenceRunBackoutMixin
from giljo_mcp.services.sequence_run_service import SequenceRunService


_BACKOUT_WRITERS = ("stop_chain", "deactivate_chain")


def test_service_inherits_the_backout_mixin() -> None:
    assert issubclass(SequenceRunService, SequenceRunBackoutMixin)


def test_both_writers_resolve_on_the_service() -> None:
    for name in _BACKOUT_WRITERS:
        assert callable(getattr(SequenceRunService, name, None)), (
            f"{name} must still resolve on SequenceRunService — callers (the REST "
            f"endpoints and the MCP accessor) reach it through the service, not the mixin"
        )


def test_the_writers_are_owned_by_the_mixin_not_duplicated_on_the_service() -> None:
    for name in _BACKOUT_WRITERS:
        assert name in SequenceRunBackoutMixin.__dict__, f"{name} must be defined on the mixin"
        assert name not in SequenceRunService.__dict__, (
            f"{name} is defined on BOTH SequenceRunService and SequenceRunBackoutMixin — "
            f"the move left a duplicate, so the two definitions can now diverge"
        )


def _called_names(func) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Attribute):
                names.add(target.attr)
            elif isinstance(target, ast.Name):
                names.add(target.id)
    return names


def test_stop_chain_is_not_the_destructive_rewind() -> None:
    called = _called_names(SequenceRunBackoutMixin.stop_chain)

    assert "reset_to_prestage" not in called, (
        "stop_chain must not call reset_to_prestage — it hard-deletes the member's agent "
        "jobs and its audit trail; that is deactivate_chain's job, not the Stop button's"
    )
    assert "terminate_project" in called, "the member underway is stood down via the owning terminate_project writer"


def test_the_guard_above_is_not_vacuous() -> None:
    assert "reset_to_prestage" in _called_names(SequenceRunBackoutMixin.deactivate_chain)
