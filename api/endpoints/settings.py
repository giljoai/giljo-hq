# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session, require_admin
from giljo_mcp.execution_mode_default import (
    EXECUTION_MODE_DEFAULT_CHOICES,
    EXECUTION_MODE_DEFAULT_KEY,
    STAGE_MODE_ASK,
)
from giljo_mcp.models import User
from giljo_mcp.services.handover_template import (
    DEFAULT_HANDOVER_TEMPLATE,
    HANDOVER_TEMPLATE_MAX_CHARS,
    HANDOVER_TEMPLATE_SETTING_KEY,
    normalize_handover_template,
    require_template_within_cap,
    resolve_handover_template,
    template_is_default,
)
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


class ExecutionModeDefaultResponse(BaseModel):
    """The account's standing answer to the one question staging asks (FE-9555)."""

    execution_mode_default: str


class ExecutionModeDefaultUpdate(BaseModel):
    """Set the account-level execution-mode default."""

    execution_mode_default: str = Field(
        description="One of: " + ", ".join(EXECUTION_MODE_DEFAULT_CHOICES),
    )

    @field_validator("execution_mode_default")
    @classmethod
    def _must_be_a_known_choice(cls, value: str) -> str:
        if value not in EXECUTION_MODE_DEFAULT_CHOICES:
            raise ValueError(f"must be one of {list(EXECUTION_MODE_DEFAULT_CHOICES)}")
        return value


class HandoverTemplateResponse(BaseModel):
    """The account's handover template, as it will be used (BE-9643a).

    ``handover_template`` is what BOTH doors start a handover from -- the dialog
    pre-fills it and the generated retirement prompt carries it -- so it is always
    returned with the required headings present, whatever the stored row holds.
    ``is_default`` is the server's answer to "is this account on the shipped text",
    so the dashboard does not need a second definition of default to decide whether
    to offer Reset.
    """

    handover_template: str = Field(description="The template every new handover on this account starts from.")
    is_default: bool = Field(description="True when the account has never set one, or has reset to the shipped text.")


class HandoverTemplateUpdate(BaseModel):
    """Replace the account's handover template."""

    handover_template: str = Field(
        description=(
            "Free text every handover starts from. Add whatever sections you want; the three "
            "headings the server requires are appended if you leave one out, so the template "
            "can never ask for a handover the server would refuse. Limit "
            f"{HANDOVER_TEMPLATE_MAX_CHARS} characters."
        ),
    )




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

    from api.app_state import GILJO_MODE, state

    if GILJO_MODE == "saas":
        tenant_service = TenantConfigurationService(db_manager=state.db_manager, tenant_key=current_user.tenant_key)
        override = await tenant_service.get_agent_silence_threshold_minutes()
        if override is not None:
            return AgentSilenceThresholdResponse(agent_silence_threshold_minutes=override)

    deployment_default = await SystemSettingsService(db).get_agent_silence_threshold_minutes()
    return AgentSilenceThresholdResponse(
        agent_silence_threshold_minutes=deployment_default or DEFAULT_SILENCE_THRESHOLD_MINUTES
    )


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


@router.get(
    "/execution-mode-default",
    response_model=ExecutionModeDefaultResponse,
    summary="Get the account execution-mode default",
    description="Whether staging asks how the work should run every time, or uses a set mode.",
)
async def get_execution_mode_default(
    current_user: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db_session)
) -> ExecutionModeDefaultResponse:
    """Read the account's execution-mode default (all authenticated users).

    Unset means ``ask`` -- the value the staging refusal keys on. Shipping any
    other default here would put FE-9555's silent pick straight back, just from
    a different file.
    """
    logger.debug("User %s retrieving execution-mode default", sanitize(current_user.username))

    service = SettingsService(db, current_user.tenant_key)
    stored = await service.get_setting_value("general", EXECUTION_MODE_DEFAULT_KEY, default=STAGE_MODE_ASK)

    if stored not in EXECUTION_MODE_DEFAULT_CHOICES:
        stored = STAGE_MODE_ASK

    return ExecutionModeDefaultResponse(execution_mode_default=str(stored))


@router.put(
    "/execution-mode-default",
    response_model=ExecutionModeDefaultResponse,
    summary="Set the account execution-mode default",
    description="Set to 'ask' to be asked every staging, or name a mode to stop being asked.",
)
async def update_execution_mode_default(
    request: ExecutionModeDefaultUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> ExecutionModeDefaultResponse:
    """Set the account's execution-mode default (admin only, like every other write here).

    Read-modify-write, for the same reason the headless toggle does it: the
    `general` category holds other keys, and a blind category overwrite would
    drop every one of them.
    """
    logger.info(
        "Admin %s setting execution-mode default to %s",
        sanitize(current_user.username),
        sanitize(request.execution_mode_default),
    )

    service = SettingsService(db, current_user.tenant_key)
    general = await service.get_settings("general")
    general[EXECUTION_MODE_DEFAULT_KEY] = request.execution_mode_default
    await service.update_settings("general", general)

    return ExecutionModeDefaultResponse(execution_mode_default=request.execution_mode_default)


@router.get(
    "/handover-template",
    response_model=HandoverTemplateResponse,
    summary="Get the account handover template",
    description="The text every new handover on this account starts from.",
)
async def get_handover_template(
    current_user: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db_session)
) -> HandoverTemplateResponse:
    """Read the account's handover template (all authenticated users).

    Readable by anyone who can see the account, exactly like the execution-mode
    default next to it: the handover dialog pre-fills from this, and a read that
    403s would leave the author with an empty editor and no way to know why. The
    WRITES below are admin-gated.

    Never returns the raw stored row. A row written by hand, or before this endpoint
    existed, can be missing a required heading; completing it on read is what stops
    one such row from breaking every handover written after it.
    """
    logger.debug("User %s retrieving the handover template", sanitize(current_user.username))

    service = SettingsService(db, current_user.tenant_key)
    stored = await service.get_setting_value("general", HANDOVER_TEMPLATE_SETTING_KEY, default="")

    return HandoverTemplateResponse(
        handover_template=resolve_handover_template(stored),
        is_default=template_is_default(stored),
    )


@router.put(
    "/handover-template",
    response_model=HandoverTemplateResponse,
    summary="Set the account handover template",
    description="Replace the text every new handover starts from. Required headings are added if omitted.",
)
async def update_handover_template(
    request: HandoverTemplateUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> HandoverTemplateResponse:
    """Set the account's handover template (admin only, like every other write here).

    The operator may add sections; the three required headings are not theirs to
    remove. One missing is APPENDED rather than refused -- a template that omitted
    one would hand every author a document the server then rejects, for a reason the
    author, who did exactly what the template said, cannot see.

    Read-modify-write, for the same reason the execution-mode default does it: the
    `general` category holds other keys and a blind category overwrite would drop
    every one of them.
    """
    logger.info("Admin %s updating the handover template", sanitize(current_user.username))

    require_template_within_cap(request.handover_template, operation="update_handover_template")
    stored = normalize_handover_template(request.handover_template)

    service = SettingsService(db, current_user.tenant_key)
    general = await service.get_settings("general")
    general[HANDOVER_TEMPLATE_SETTING_KEY] = stored
    await service.update_settings("general", general)

    return HandoverTemplateResponse(
        handover_template=resolve_handover_template(stored),
        is_default=template_is_default(stored),
    )


@router.post(
    "/handover-template/reset",
    response_model=HandoverTemplateResponse,
    summary="Reset the account handover template",
    description="Restore the shipped default template.",
)
async def reset_handover_template(
    current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db_session)
) -> HandoverTemplateResponse:
    """Restore the shipped default (admin only).

    Its own path rather than "PUT the default text back": the caller would have to
    hold a copy of the default to do that, which is a second definition of the
    default living in the frontend, drifting the first time either changes. The key
    is CLEARED rather than written with the default, so an account that resets keeps
    tracking the shipped text as it improves instead of freezing today's copy.
    """
    logger.info("Admin %s reset the handover template to the default", sanitize(current_user.username))

    service = SettingsService(db, current_user.tenant_key)
    general = await service.get_settings("general")
    general.pop(HANDOVER_TEMPLATE_SETTING_KEY, None)
    await service.update_settings("general", general)

    return HandoverTemplateResponse(handover_template=DEFAULT_HANDOVER_TEMPLATE, is_default=True)
