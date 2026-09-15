# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from fastapi import APIRouter

from . import crud, history, preview


router = APIRouter(prefix="/api/v1/templates", tags=["templates"])

router.include_router(crud.router)
router.include_router(history.router)
router.include_router(preview.router)

__all__ = ["router"]
