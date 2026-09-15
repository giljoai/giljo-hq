# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from giljo_mcp.services import project_closeout_readiness as readiness
from giljo_mcp.services import project_closeout_service as service


def test_dataclasses_re_exported_identically():
    assert service.AgentReadinessFinding is readiness.AgentReadinessFinding
    assert service.CloseoutReadinessReport is readiness.CloseoutReadinessReport


def test_batch_helpers_live_in_readiness_module():
    import inspect

    assert inspect.iscoroutinefunction(readiness.incomplete_todos_by_jobs)
    assert inspect.iscoroutinefunction(readiness.pending_approval_ids_by_execution)
