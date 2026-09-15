# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from fastapi import APIRouter

from . import routes


router = APIRouter(prefix="/api/v1/task-statuses", tags=["task-statuses"])
router.include_router(routes.router)

__all__ = ["router"]
