# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Settings API endpoints for Giljo HQ.

Provides REST API for system settings management:
- GET/PUT /general - General system settings
- GET /database - Database settings (read-only)

All endpoints enforce multi-tenant isolation and role-based access control.
Handover 0506: Settings endpoints implementation.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session, require_admin
from giljo_mcp.models import User
from giljo_mcp.services.settings_service import (
    DEFAULT_AGENT_CHECKIN_CADENCE_MINUTES,
    SettingsService,
    SystemSettingsService,
)
from giljo_mcp.services.silence_detector import DEFAULT_SILENCE_THRESHOLD_MINUTES
from giljo_mcp.services.tenant_configuration_service import TenantConfigurationService
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)
router = APIRouter()

# Pydantic Models


class SettingsUpdate(BaseModel):
    """Settings update request - settings dict required"""

    settings: dict[str, Any]


class SettingsResponse(BaseModel):
    """Settings response - wraps settings dict"""

    settings: dict[str, Any]


class SettingsUpdateResponse(BaseModel):
    """Settings update response - includes success message"""

    settings: dict[str, Any]
    message: str


class AgentSilenceThresholdUpdate(BaseModel):
    """Update request for the deployment-wide agent silence threshold."""

    agent_silence_threshold_minutes: int = Field(ge=1)


class AgentSilenceThresholdResponse(BaseModel):
    """Deployment-wide agent silence threshold response."""

    agent_silence_threshold_minutes: int


class AgentSilenceThresholdUpdateResponse(AgentSilenceThresholdResponse):
    """Deployment-wide agent silence threshold update response."""

    message: str


class AgentCheckinCadenceUpdate(BaseModel):
    """Update request for the account-level agent check-in cadence (FE-9296b)."""

    agent_checkin_cadence_minutes: int = Field(ge=1)


class AgentCheckinCadenceResponse(BaseModel):
    """Account-level agent check-in cadence response."""

    agent_checkin_cadence_minutes: int


class AgentCheckinCadenceUpdateResponse(AgentCheckinCadenceResponse):
    """Account-level agent check-in cadence update response."""

    message: str


# API Endpoints


@router.get(
    "/general",
    response_model=SettingsResponse,
    summary="Get general settings",
    description="Get general system settings for current tenant",
)
async def get_general_settings(
    current_user: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db_session)
) -> SettingsResponse:
    """Get general settings - accessible to all authenticated users"""
    logger.debug("User %s retrieving general settings", sanitize(current_user.username))

    service = SettingsService(db, current_user.tenant_key)
    settings = await service.get_settings("general")

    return SettingsResponse(settings=settings)


# TENANT-LEVEL
@router.put(
    "/general",
    response_model=SettingsUpdateResponse,
    summary="Update general settings",
    description="Update general system settings (admin only)",
)
async def update_general_settings(
    request: SettingsUpdate, current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db_session)
) -> SettingsUpdateResponse:
    """Update general settings - admin only"""
    logger.info("Admin %s updating general settings", sanitize(current_user.username))

    service = SettingsService(db, current_user.tenant_key)
    settings = await service.update_settings("general", request.settings)

    return SettingsUpdateResponse(settings=settings, message="Settings updated successfully")


# CE: server-global threshold in system_settings (unchanged). SaaS (FE-9241): this
# tenant's own override in `configurations` if set, else the deployment-wide default.
@router.get(
    "/system/agent-silence-threshold",
    response_model=AgentSilenceThresholdResponse,
    summary="Get the agent silence threshold",
    description="CE: the server-global threshold in minutes. SaaS: this tenant's own "
    "override if set, else the deployment-wide default.",
)
async def get_agent_silence_threshold(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> AgentSilenceThresholdResponse:
    logger.debug("User %s retrieving agent silence threshold", sanitize(current_user.username))

    # Mode gate evaluated at request time so tests can patch api.app_state.GILJO_MODE
    # without re-importing this module (matches api/endpoints/tenant_data.py).
    from api.app_state import GILJO_MODE, state

    if GILJO_MODE == "saas":
        tenant_service = TenantConfigurationService(db_manager=state.db_manager, tenant_key=current_user.tenant_key)
        override = await tenant_service.get_agent_silence_threshold_minutes()
        if override is not None:
            return AgentSilenceThresholdResponse(agent_silence_threshold_minutes=override)

    # CE always reaches here; SaaS only when no tenant override is set (fallback).
    deployment_default = await SystemSettingsService(db).get_agent_silence_threshold_minutes()
    return AgentSilenceThresholdResponse(
        agent_silence_threshold_minutes=deployment_default or DEFAULT_SILENCE_THRESHOLD_MINUTES
    )


# CE: writes the server-global threshold in system_settings (unchanged, admin only).
# SaaS (FE-9241): writes this tenant's own override in `configurations` (admin only —
# every SaaS tenant's sole user is provisioned with role="admin", ADR-009 single-user).
@router.put(
    "/system/agent-silence-threshold",
    response_model=AgentSilenceThresholdUpdateResponse,
    summary="Update the agent silence threshold",
    description="CE: the server-global threshold in minutes (admin only). SaaS: this "
    "tenant's own override (admin only).",
)
async def update_agent_silence_threshold(
    request: AgentSilenceThresholdUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> AgentSilenceThresholdUpdateResponse:
    logger.info("Admin %s updating agent silence threshold", sanitize(current_user.username))

    from api.app_state import GILJO_MODE, state

    if GILJO_MODE == "saas":
        tenant_service = TenantConfigurationService(db_manager=state.db_manager, tenant_key=current_user.tenant_key)
        threshold = await tenant_service.set_agent_silence_threshold_minutes(request.agent_silence_threshold_minutes)
        return AgentSilenceThresholdUpdateResponse(
            agent_silence_threshold_minutes=threshold,
            message="Settings updated successfully",
        )

    service = SystemSettingsService(db)
    threshold = await service.update_agent_silence_threshold_minutes(request.agent_silence_threshold_minutes)

    return AgentSilenceThresholdUpdateResponse(
        agent_silence_threshold_minutes=threshold,
        message="Settings updated successfully",
    )


# FE-9296b: the account-level "how often should agents check in" default that
# replaced the per-project auto check-in slider. Hosted exactly like the silence
# threshold above: CE reads/writes the server-global value in system_settings;
# SaaS reads/writes this tenant's own override in `configurations`.
@router.get(
    "/system/agent-checkin-cadence",
    response_model=AgentCheckinCadenceResponse,
    summary="Get the agent check-in cadence",
    description="CE: the server-global cadence in minutes. SaaS: this tenant's own "
    "override if set, else the deployment-wide default.",
)
async def get_agent_checkin_cadence(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> AgentCheckinCadenceResponse:
    logger.debug("User %s retrieving agent check-in cadence", sanitize(current_user.username))

    from api.app_state import GILJO_MODE, state

    if GILJO_MODE == "saas":
        tenant_service = TenantConfigurationService(db_manager=state.db_manager, tenant_key=current_user.tenant_key)
        override = await tenant_service.get_agent_checkin_cadence_minutes()
        if override is not None:
            return AgentCheckinCadenceResponse(agent_checkin_cadence_minutes=override)

    # CE always reaches here; SaaS only when no tenant override is set (fallback).
    deployment_default = await SystemSettingsService(db).get_agent_checkin_cadence_minutes()
    return AgentCheckinCadenceResponse(
        agent_checkin_cadence_minutes=deployment_default or DEFAULT_AGENT_CHECKIN_CADENCE_MINUTES
    )


@router.put(
    "/system/agent-checkin-cadence",
    response_model=AgentCheckinCadenceUpdateResponse,
    summary="Update the agent check-in cadence",
    description="CE: the server-global cadence in minutes (admin only). SaaS: this tenant's own override (admin only).",
)
async def update_agent_checkin_cadence(
    request: AgentCheckinCadenceUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> AgentCheckinCadenceUpdateResponse:
    logger.info("Admin %s updating agent check-in cadence", sanitize(current_user.username))

    from api.app_state import GILJO_MODE, state

    if GILJO_MODE == "saas":
        tenant_service = TenantConfigurationService(db_manager=state.db_manager, tenant_key=current_user.tenant_key)
        cadence = await tenant_service.set_agent_checkin_cadence_minutes(request.agent_checkin_cadence_minutes)
        return AgentCheckinCadenceUpdateResponse(
            agent_checkin_cadence_minutes=cadence,
            message="Settings updated successfully",
        )

    service = SystemSettingsService(db)
    cadence = await service.update_agent_checkin_cadence_minutes(request.agent_checkin_cadence_minutes)

    return AgentCheckinCadenceUpdateResponse(
        agent_checkin_cadence_minutes=cadence,
        message="Settings updated successfully",
    )


@router.get(
    "/database",
    response_model=SettingsResponse,
    summary="Get database settings",
    description="Get database configuration for current tenant (read-only)",
)
async def get_database_settings(
    current_user: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db_session)
) -> SettingsResponse:
    """Get database settings - read-only for all authenticated users"""
    logger.debug("User %s retrieving database settings", sanitize(current_user.username))

    service = SettingsService(db, current_user.tenant_key)
    settings = await service.get_settings("database")

    return SettingsResponse(settings=settings)
