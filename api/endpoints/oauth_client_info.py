# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import inspect
import ipaddress
import os
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.services.oauth_cimd import is_cimd_client_id, resolve_cimd_client
from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID, OAuthService, ResolvedClient, get_client_resolver


router = APIRouter()

KNOWN_CLIENT_IDS_ENV = "GILJO_OAUTH_KNOWN_CLIENT_IDS"
KNOWN_CLIENT_HOSTS_ENV = "GILJO_OAUTH_KNOWN_CLIENT_HOSTS"

DEFAULT_KNOWN_CLIENT_HOSTS: frozenset[str] = frozenset(
    {"claude.ai", "chatgpt.com", "vscode.dev", "insiders.vscode.dev", "cursor.com", "opencode.ai"}
)

_NO_CONTROL_CHARS = r"^[^\x00-\x1f\x7f]+$"
_HOST_AMBIGUOUS = re.compile(r"[\x00-\x20\x7f-\x9f\u2028\u2029\\]")


def _env_list(name: str) -> list[str]:
    return [entry.strip() for entry in os.environ.get(name, "").split(",") if entry.strip()]


def known_client_hosts() -> frozenset[str]:
    if KNOWN_CLIENT_HOSTS_ENV in os.environ:
        return frozenset(host.lower() for host in _env_list(KNOWN_CLIENT_HOSTS_ENV))
    return DEFAULT_KNOWN_CLIENT_HOSTS


def _on_known_site(uri: str, hosts: frozenset[str]) -> bool:
    if _HOST_AMBIGUOUS.search(uri):
        return False
    try:
        parts = urlsplit(uri)
        port = parts.port
    except ValueError:
        return False
    host = parts.hostname or ""
    return (
        parts.scheme == "https"
        and port in (None, 443)
        and parts.username is None
        and parts.password is None
        and host.isascii()
        and host in hosts
    )


def is_known_client(resolved: ResolvedClient) -> bool:
    client_id = resolved.client_id
    if client_id == BUILTIN_CLIENT_ID or client_id in _env_list(KNOWN_CLIENT_IDS_ENV):
        return True
    hosts = known_client_hosts()
    if is_cimd_client_id(client_id) and _on_known_site(client_id, hosts):
        return True
    uris = resolved.redirect_uris
    return bool(uris) and all(_on_known_site(uri, hosts) for uri in uris)


def display_host(uri: str) -> str | None:
    if _HOST_AMBIGUOUS.search(uri):
        return None
    try:
        host = urlsplit(uri).hostname
    except ValueError:
        return None
    return host if host and host.isascii() else None


def is_local_host(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


async def resolve_consent_client(client_id: str, tenant_key: str) -> ResolvedClient | None:
    if is_cimd_client_id(client_id):
        return await resolve_cimd_client(client_id)
    resolved = get_client_resolver()(client_id, tenant_key)
    if inspect.isawaitable(resolved):
        resolved = await resolved
    return resolved


async def resolve_client_name(client_id: str, tenant_key: str) -> str | None:
    resolved = await resolve_consent_client(client_id, tenant_key)
    return resolved.client_name if resolved is not None else None


class OAuthConsentClientResponse(BaseModel):
    """What the consent screen shows about the application asking for access."""

    client_id: str = Field(description="The client identifier that was looked up.")
    client_name: str = Field(description="The name the application registered under. Chosen by the application.")
    verified: bool = Field(description="True when this server recognizes the application; its name is then trusted.")
    redirect_host: str | None = Field(
        default=None, description="The host the access will be sent to, when a redirect URI was given."
    )
    redirect_is_local: bool = Field(
        default=False, description="True when the access goes to an app on the user's own computer."
    )
    client_id_host: str | None = Field(
        default=None, description="For an application identified by a URL, the host that published it."
    )


@router.get("/authorize/client", response_model=OAuthConsentClientResponse, tags=["oauth"])
async def get_authorize_client(
    client_id: str = Query(..., min_length=1, max_length=2048, pattern=_NO_CONTROL_CHARS),
    redirect_uri: str | None = Query(default=None, min_length=1, max_length=2048, pattern=_NO_CONTROL_CHARS),
    current_user: User = Depends(get_current_active_user),
):
    """Describe the application asking for consent.

    Returns the name it registered under, whether this server recognizes it, and the host
    the access will be sent to, so the consent screen can show where a grant really goes.

    Raises:
        HTTPException 404: If no application is registered under ``client_id``.
        HTTPException 400: If ``redirect_uri`` is not registered for the application.
    """
    resolved = await resolve_consent_client(client_id, current_user.tenant_key)
    if resolved is None or not resolved.client_name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    redirect_host = None
    if redirect_uri is not None:
        if not OAuthService._redirect_uri_matches(resolved, redirect_uri):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This redirect address is not registered for the application.",
            )
        redirect_host = display_host(redirect_uri)
        if redirect_host is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This redirect address cannot be shown on the consent screen.",
            )
    return OAuthConsentClientResponse(
        client_id=client_id,
        client_name=resolved.client_name,
        verified=is_known_client(resolved),
        redirect_host=redirect_host,
        redirect_is_local=is_local_host(redirect_host),
        client_id_host=display_host(client_id) if is_cimd_client_id(client_id) else None,
    )
