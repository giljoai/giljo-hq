# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from fastapi import APIRouter

from . import completion, crud, lifecycle, series, status


router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

router.include_router(series.router)
router.include_router(crud.router)
router.include_router(lifecycle.router)
router.include_router(status.router)
router.include_router(completion.router)

__all__ = ["router"]
