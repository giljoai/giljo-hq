# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from fastapi import APIRouter

from . import agent_assignments, crud, lifecycle, memory, tuning, vision


router = APIRouter(prefix="/api/v1/products", tags=["Products"])

router.include_router(lifecycle.router)
router.include_router(crud.router)
router.include_router(vision.router)
router.include_router(memory.router)
router.include_router(tuning.router)
router.include_router(agent_assignments.router)

__all__ = ["router"]
