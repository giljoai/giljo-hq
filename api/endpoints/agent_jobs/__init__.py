# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from fastapi import APIRouter

from . import (
    lifecycle,
    messages,
    operations,
    orchestration,
    simple_handover,
    status,
)


router = APIRouter(prefix="/api/agent-jobs", tags=["agent-jobs"])

router.include_router(lifecycle.router)
router.include_router(status.router)
router.include_router(orchestration.router)
router.include_router(simple_handover.router)
router.include_router(messages.router)

jobs_router = APIRouter(prefix="/api/jobs", tags=["job-operations"])
jobs_router.include_router(operations.router)

__all__ = ["jobs_router", "router"]
