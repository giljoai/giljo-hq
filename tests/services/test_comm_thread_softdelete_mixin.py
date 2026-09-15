# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services._comm_thread_softdelete_mixin import CommThreadSoftDeleteMixin
from giljo_mcp.services.comm_thread_service import CommThreadService


_LIFECYCLE_API = ("delete_thread", "restore_thread", "list_deleted_threads", "purge_expired_deleted_threads")


def test_service_inherits_the_soft_delete_mixin():
    assert issubclass(CommThreadService, CommThreadSoftDeleteMixin)


def test_the_lifecycle_api_survived_the_move():
    for name in _LIFECYCLE_API:
        assert hasattr(CommThreadService, name), f"{name} vanished from the service API"


def test_each_method_is_served_by_the_mixin_not_redefined():
    for name in _LIFECYCLE_API:
        assert getattr(CommThreadService, name) is getattr(CommThreadSoftDeleteMixin, name)
