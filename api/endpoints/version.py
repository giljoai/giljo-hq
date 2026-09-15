# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import APIRouter
from pydantic import BaseModel

from giljo_mcp.services.version_service import get_version_info


logger = logging.getLogger(__name__)

router = APIRouter()


class VersionResponse(BaseModel):
    """Response schema for GET /api/version/latest."""

    installed_version: str
    latest_version: str | None = None
    latest_tarball_url: str | None = None
    latest_sha256: str | None = None
    update_available: bool = False
    checked_at: str | None = None


@router.get("/latest", response_model=VersionResponse)
async def get_latest_version() -> VersionResponse:
    """Return installed version and latest available version from GitHub.

    This endpoint is intentionally unauthenticated so that installers
    and update scripts can check for new versions before auth is set up.
    """
    info = await get_version_info()
    return VersionResponse(
        installed_version=info.installed_version,
        latest_version=info.latest_version,
        latest_tarball_url=info.latest_tarball_url,
        latest_sha256=info.latest_sha256,
        update_available=info.update_available,
        checked_at=info.checked_at,
    )
