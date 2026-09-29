# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.dependencies import get_db_session, require_admin
from giljo_mcp.models import User
from giljo_mcp.services.settings_service import SettingsService
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)
router = APIRouter()



class CookieDomainsResponse(BaseModel):
    """Response model for cookie domain whitelist."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"domains": ["localhost", "example.com", "subdomain.example.com"]}}
    )

    domains: list[str] = Field(description="List of whitelisted cookie domains")


class AddCookieDomainRequest(BaseModel):
    """Request model for adding a domain to cookie whitelist."""

    model_config = ConfigDict(json_schema_extra={"example": {"domain": "example.com"}})

    domain: str = Field(
        min_length=3, max_length=255, description="Domain name to whitelist (e.g., 'localhost', 'example.com')"
    )

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        domain = v.lower().strip()

        if len(domain) < 3:
            raise ValueError("Domain must be at least 3 characters long")
        if len(domain) > 255:
            raise ValueError("Domain must not exceed 255 characters")

        if re.match(r"^[\d.]+$", domain):
            raise ValueError("IP addresses are automatically allowed - only add domain names")

        domain_pattern = (
            r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
        )

        if not re.match(domain_pattern, domain):
            raise ValueError(
                "Invalid domain format. Must be a valid DNS hostname "
                "(e.g., 'localhost', 'example.com', 'subdomain.example.com')"
            )

        return domain


class RemoveCookieDomainRequest(BaseModel):
    """Request model for removing a domain from cookie whitelist."""

    model_config = ConfigDict(json_schema_extra={"example": {"domain": "example.com"}})

    domain: str = Field(min_length=3, max_length=255, description="Domain name to remove from whitelist")


class HeadlessLaunchResponse(BaseModel):
    """Response model for the account-wide Headless-vs-HITL launch toggle."""

    model_config = ConfigDict(json_schema_extra={"example": {"allow_headless_launch": True}})

    allow_headless_launch: bool = Field(
        description="False (the default) = HITL: a human must press Implement, or answer an approval, "
        "in the dashboard. True = Headless: turning this on says your harness's own permission "
        "prompt for that call IS your approval, and running that harness with a bypass/skip-permissions "
        "flag removes the ask -- so a trusted CLI/OAuth agent may self-advance the implement gate with "
        "nobody having actually been asked."
    )


class HeadlessLaunchUpdateRequest(BaseModel):
    """Request model for updating the account-wide Headless-vs-HITL launch toggle."""

    model_config = ConfigDict(json_schema_extra={"example": {"allow_headless_launch": True}})

    allow_headless_launch: bool = Field(
        description="False (the default) enforces the human Implement step; True opts into Headless, "
        "where your harness's own permission prompt for that call becomes your approval."
    )




@router.get("/settings/cookie-domains", response_model=CookieDomainsResponse)
async def get_cookie_domains(
    current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db_session)
) -> CookieDomainsResponse:
    """
    Get cookie domain whitelist.

    Returns list of domains allowed for cross-port cookie authentication.
    Requires admin role.

    Args:
        current_user: Current authenticated admin user
        db: Database session

    Returns:
        CookieDomainsResponse with list of whitelisted domains

    Raises:
        HTTPException: 403 if user is not admin
    """
    logger.info("Admin %s retrieving cookie domain whitelist", sanitize(current_user.username))

    service = SettingsService(db, current_user.tenant_key)
    security = await service.get_settings("security")
    domains = security.get("cookie_domain_whitelist", [])

    logger.debug("Cookie domain whitelist: %s", domains)
    return CookieDomainsResponse(domains=domains)


@router.post("/settings/cookie-domains", response_model=CookieDomainsResponse, status_code=status.HTTP_201_CREATED)
async def add_cookie_domain(
    request: AddCookieDomainRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> CookieDomainsResponse:
    """
    Add domain to cookie whitelist.

    Adds a domain to the whitelist for cross-port cookie authentication.
    If domain already exists, operation is idempotent (no error).
    Requires admin role.

    Args:
        request: Domain to add
        current_user: Current authenticated admin user
        db: Database session

    Returns:
        Updated CookieDomainsResponse with all whitelisted domains

    Raises:
        HTTPException: 400 if domain validation fails
        HTTPException: 403 if user is not admin
    """
    domain = request.domain.lower().strip()
    logger.info("Admin %s adding cookie domain: %s", sanitize(current_user.username), sanitize(domain))

    service = SettingsService(db, current_user.tenant_key)
    security = await service.get_settings("security")
    domains: list[str] = security.get("cookie_domain_whitelist", [])

    if domain not in domains:
        domains.append(domain)
        logger.info("Added domain to whitelist: %s", sanitize(domain))
    else:
        logger.debug("Domain already in whitelist: %s", sanitize(domain))

    security["cookie_domain_whitelist"] = domains
    await service.update_settings("security", security)

    logger.info("Cookie domain whitelist updated. Total domains: %d", len(domains))
    return CookieDomainsResponse(domains=domains)


@router.delete("/settings/cookie-domains", response_model=CookieDomainsResponse)
async def remove_cookie_domain(
    request: RemoveCookieDomainRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> CookieDomainsResponse:
    """
    Remove domain from cookie whitelist.

    Removes a domain from the whitelist for cross-port cookie authentication.
    Requires admin role.

    Args:
        request: Domain to remove
        current_user: Current authenticated admin user
        db: Database session

    Returns:
        Updated CookieDomainsResponse with remaining whitelisted domains

    Raises:
        HTTPException: 403 if user is not admin
        HTTPException: 404 if domain not found in whitelist
    """
    domain = request.domain.lower().strip()
    logger.info("Admin %s removing cookie domain: %s", sanitize(current_user.username), sanitize(domain))

    service = SettingsService(db, current_user.tenant_key)
    security = await service.get_settings("security")
    domains: list[str] = security.get("cookie_domain_whitelist", [])

    if domain not in domains:
        logger.warning("Domain not found in whitelist: %s", sanitize(domain))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Domain '{domain}' not found in whitelist")

    domains.remove(domain)
    logger.info("Removed domain from whitelist: %s", sanitize(domain))

    security["cookie_domain_whitelist"] = domains
    await service.update_settings("security", security)

    logger.info("Cookie domain whitelist updated. Remaining domains: %d", len(domains))
    return CookieDomainsResponse(domains=domains)


@router.get("/settings/headless-launch", response_model=HeadlessLaunchResponse)
async def get_headless_launch(
    current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db_session)
) -> HeadlessLaunchResponse:
    """Get the account-wide setting controlling whether a connected agent may
    advance the implement gate.

    BE-9670b: off (False) by default. Admin-gated and tenant-scoped. Requires
    admin role.
    """
    logger.debug("Admin %s retrieving headless-launch toggle", sanitize(current_user.username))

    service = SettingsService(db, current_user.tenant_key)
    allow = await service.get_setting_value("security", "allow_headless_launch", default=False)

    return HeadlessLaunchResponse(allow_headless_launch=bool(allow))


@router.put("/settings/headless-launch", response_model=HeadlessLaunchResponse)
async def update_headless_launch(
    request: HeadlessLaunchUpdateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> HeadlessLaunchResponse:
    """Set the account-wide Headless-vs-HITL launch toggle (admin only).

    HITL (False) is the platform default: the server does not authorize
    implementation early for a jwt/OAuth agent session -- the human Implement step
    is enforced at the MCP launch gate. This endpoint is how a tenant opts IN to
    Headless (True): a harness's own permission prompt for a gated call then
    counts as the human's approval, so running that harness with a
    bypass/skip-permissions flag removes the ask. This is a server-side
    authorization control; it does not attempt to constrain client-local
    execution. Read-modify-write preserves the sibling ``security`` keys, and
    stamps ``allow_headless_launch_explicit=True`` so this deliberate write is
    distinguishable from an incidental one made by another security writer.
    """
    logger.info(
        "Admin %s setting headless-launch toggle to %s",
        sanitize(current_user.username),
        sanitize(request.allow_headless_launch),
    )

    service = SettingsService(db, current_user.tenant_key)
    security = await service.get_settings("security")
    security["allow_headless_launch"] = request.allow_headless_launch
    security["allow_headless_launch_explicit"] = True
    await service.update_settings("security", security)

    return HeadlessLaunchResponse(allow_headless_launch=request.allow_headless_launch)
