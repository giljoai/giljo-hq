# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9289b — the soft-delete lifecycle is served by CommThreadSoftDeleteMixin.

The extraction out of ``CommThreadService`` was a PURE MOVE, so the behavioural
coverage lives where it always did (``test_be6130b_comm_thread_recover``,
``test_tsk6132_softdelete_reaper``) and is unchanged because the behaviour is unchanged.

What a relocation CAN silently break is the composition. If the mixin is ever dropped
from the service's bases, or a method is quietly redefined on the service so the mixin
copy goes stale, the failure surfaces somewhere else as an obscure AttributeError or as
two diverging implementations. These assertions name the cause instead.

Parallel-safe: pure import-level assertions, no DB, no module-level mutable state.
"""

from __future__ import annotations

from giljo_mcp.services._comm_thread_softdelete_mixin import CommThreadSoftDeleteMixin
from giljo_mcp.services.comm_thread_service import CommThreadService


_LIFECYCLE_API = ("delete_thread", "restore_thread", "list_deleted_threads", "purge_expired_deleted_threads")


def test_service_inherits_the_soft_delete_mixin():
    assert issubclass(CommThreadService, CommThreadSoftDeleteMixin)


def test_the_lifecycle_api_survived_the_move():
    """The public service surface is unchanged — that is what makes the move invisible
    to every existing caller (MCP tools, REST routes, the reaper background task)."""
    for name in _LIFECYCLE_API:
        assert hasattr(CommThreadService, name), f"{name} vanished from the service API"


def test_each_method_is_served_by_the_mixin_not_redefined():
    """Served BY the mixin, never shadowed on the service — one source of truth. A
    redefinition would leave the mixin copy dead while still looking authoritative."""
    for name in _LIFECYCLE_API:
        assert getattr(CommThreadService, name) is getattr(CommThreadSoftDeleteMixin, name)
