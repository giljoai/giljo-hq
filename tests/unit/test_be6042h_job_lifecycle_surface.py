# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import inspect
from unittest.mock import MagicMock

from giljo_mcp.services.job_lifecycle_service import JobLifecycleService


PUBLIC_ASYNC_METHODS = frozenset({"spawn_job"})


def _service() -> JobLifecycleService:
    return JobLifecycleService(db_manager=MagicMock(), tenant_manager=MagicMock())


def test_public_import_resolves():
    from giljo_mcp.services.job_lifecycle_service import (
        JobLifecycleService as Imported,
    )

    assert Imported is JobLifecycleService


def test_public_async_surface_is_exactly_spawn_job():
    service = _service()
    public_async = {
        name
        for name in dir(service)
        if not name.startswith("_") and inspect.iscoroutinefunction(getattr(service, name))
    }
    assert public_async == PUBLIC_ASYNC_METHODS


def test_spawn_job_present_callable_async():
    service = _service()
    assert hasattr(service, "spawn_job")
    assert callable(service.spawn_job)
    assert inspect.iscoroutinefunction(service.spawn_job)
