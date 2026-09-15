# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.endpoints import configuration_ssl
from giljo_mcp.auth.dependencies import get_current_active_user, require_admin, require_ce_mode
from giljo_mcp.models import User


logger = logging.getLogger(__name__)

router = APIRouter()

router.include_router(configuration_ssl.router)


class SuccessResponse(BaseModel):
    """Generic success response for operations that return a simple status message."""

    success: bool = True
    message: str


class NetworkInfoResponse(BaseModel):
    """The host IP(s) and port the server actually responds on (server-level, CE-only)."""

    hosts: list[str] = Field(..., description="Responding interface IP(s), or ['localhost'] when loopback-bound")
    host_display: str = Field(..., description="Comma-joined hosts for display")
    port: int = Field(..., description="Port the server listens on")
    bind_all: bool = Field(..., description="True when bound to all interfaces (0.0.0.0/::)")


@router.get("/")
async def get_system_configuration(
    current_user: User = Depends(get_current_active_user),
    _ce: None = Depends(require_ce_mode),
):
    """Return the full config.yaml structure (CE-only); sensitive fields masked.

    CE-gated via require_ce_mode: config.yaml is a self-hosted concept absent in
    SaaS/hosted deployments.
    """
    from giljo_mcp._config_io import read_config

    config = read_config()

    if not config:
        raise HTTPException(status_code=500, detail="config.yaml is empty or not found")

    if "database" in config and "password" in config.get("database", {}):
        config["database"]["password"] = "****" if config["database"]["password"] else ""

    if "security" in config and "api_keys" in config.get("security", {}):
        api_keys = config["security"].get("api_keys", {})
        if isinstance(api_keys, dict):
            for key in api_keys:
                if isinstance(api_keys[key], str):
                    api_keys[key] = "****"

    return config




class DatabaseConfigResponse(BaseModel):
    host: str
    port: int
    name: str
    user: str
    password_masked: str


@router.get("/database", response_model=DatabaseConfigResponse)
async def get_database_configuration(
    current_user: User = Depends(require_admin),
    _ce: None = Depends(require_ce_mode),
):
    """Get database configuration (password masked) - reads from .env file"""
    from dotenv import dotenv_values

    env_path = Path.cwd() / ".env"

    if not env_path.exists():
        raise HTTPException(status_code=404, detail=".env file not found")

    env_vars = dotenv_values(env_path)

    host = env_vars.get("DB_HOST", "localhost")
    port = int(env_vars.get("DB_PORT", "5432"))
    name = env_vars.get("DB_NAME", "giljo_mcp")
    user = env_vars.get("DB_USER", "giljo_user")
    password = env_vars.get("DB_PASSWORD", "")

    password_masked = "*" * len(password) if password else "****"

    return DatabaseConfigResponse(host=host, port=port, name=name, user=user, password_masked=password_masked)


@router.get("/frontend")
async def get_frontend_configuration(request: Request):
    """Get frontend-specific configuration (host, port, websocket URL, security flags).

    Response shape (INF-5012b): api.host/port/protocol derive from
    request.base_url (honors X-Forwarded-* via uvicorn proxy_headers), matching
    the pattern websocket.url already uses. api.port is int | null — null when
    implicit on a reverse proxy (standard 443/80), otherwise numeric (e.g. 7272
    for CE localhost). Frontend must branch on null to omit the ":port" segment.
    """
    from urllib.parse import urlparse

    from api.app_state import GILJO_MODE, state
    from giljo_mcp import __version__ as giljo_version

    if not state.config:
        raise HTTPException(status_code=503, detail="Configuration manager not available")

    api_keys_required = state.config.get_nested("features.api_keys_required", default=False)
    ssl_enabled = state.config.get_nested("features.ssl_enabled", default=False)

    base = str(request.base_url).rstrip("/")
    parsed = urlparse(base)
    api_host = parsed.hostname or "localhost"
    api_port = parsed.port
    api_protocol = parsed.scheme or ("https" if ssl_enabled else "http")

    ws_url = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    ws_protocol = "wss" if ws_url.startswith("wss://") else "ws"

    default_tenant_key = state.config.tenant.default_tenant_key or ""

    is_remote_client = _is_remote_client(request, api_host)

    return {
        "api": {
            "host": api_host,
            "port": api_port,
            "protocol": api_protocol,
            "ssl_enabled": ssl_enabled,
            "is_remote_client": is_remote_client,
        },
        "websocket": {
            "url": ws_url,
            "protocol": ws_protocol,
        },
        "security": {
            "api_keys_required": api_keys_required,
            "default_tenant_key": default_tenant_key,
        },
        "edition": {"ce": "community", "saas": "saas"}.get(GILJO_MODE, "community"),
        "giljo_mode": GILJO_MODE,
        "version": giljo_version,
    }


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


def _is_remote_client(request: Request, server_host: str) -> bool:
    client_ip = _get_client_ip(request)
    local_addresses = {"127.0.0.1", "::1", "localhost", server_host}
    return client_ip not in local_addresses


@router.get("/network-info", response_model=NetworkInfoResponse)
async def get_network_info(
    current_user: User = Depends(require_admin),
    _ce: None = Depends(require_ce_mode),
):
    """Report the host IP(s) and port the server actually responds on (server-level, CE-only).

    FE-6239 (INF-6236 follow-up): the Network settings tab used to show the
    configured external host (often "localhost") even though a LAN install binds
    0.0.0.0 and answers on every interface IP. We compute the REAL responding
    address(es): bound to all interfaces -> enumerate the machine's non-loopback
    IPv4s; bound to loopback -> "localhost"; bound to a single IP -> that IP.
    Mirrors ``api.run_api.get_default_host()`` (config services.api.host, default 0.0.0.0).
    """
    from giljo_mcp._config_io import read_config

    config = read_config()
    services = config.get("services", {}) or {}
    api_cfg = services.get("api") if isinstance(services.get("api"), dict) else {}
    api_cfg = api_cfg or {}
    bind_host = api_cfg.get("host") or "0.0.0.0"
    port = api_cfg.get("port") or (services.get("frontend") or {}).get("port") or 7272

    loopback_hosts = {"127.0.0.1", "localhost", "::1"}
    all_interface_hosts = {"0.0.0.0", "::", ""}

    if bind_host in loopback_hosts:
        hosts = ["localhost"]
        bind_all = False
    elif bind_host in all_interface_hosts:
        from installer.shared.network import get_network_ips

        hosts = get_network_ips() or ["localhost"]
        bind_all = True
    else:
        hosts = [bind_host]
        bind_all = False

    return NetworkInfoResponse(
        hosts=hosts,
        host_display=", ".join(hosts),
        port=int(port),
        bind_all=bind_all,
    )


@router.get(
    "/root-ca",
    dependencies=[Depends(get_current_active_user)],
)
async def download_root_ca():
    """Download the server's certificate as a trust anchor for remote clients.

    INF-6241: GiljoAI does not mint certificates. When an operator enables
    bring-your-own-cert HTTPS (Settings -> Network), the configured server
    certificate is its own trust anchor for a private/self-signed cert; we serve
    that exact PEM so a remote machine can trust this server. A publicly-signed
    cert (Let's Encrypt / corporate CA) needs no download -- clients already
    trust it. Returns 404 when no certificate is configured. Requires auth.
    """
    from fastapi.responses import FileResponse

    from api.endpoints.configuration_ssl import _ssl_status_from_config

    _ssl_enabled, cert_path, _key_path, has_cert = _ssl_status_from_config()
    if not has_cert or not cert_path:
        raise HTTPException(status_code=404, detail="No server certificate is configured on this server")

    return FileResponse(
        path=cert_path,
        filename="giljo-server-cert.pem",
        media_type="application/x-pem-file",
    )


@router.get("/health/database")
async def check_database_health(
    current_user: User = Depends(get_current_active_user),
    _ce: None = Depends(require_ce_mode),
):
    """Test database connection (requires authentication)"""
    from api.app_state import state

    if not state.db_manager:
        raise HTTPException(status_code=503, detail="Database manager not initialized")

    try:
        from giljo_mcp.services.tenant_configuration_service import TenantConfigurationService

        config_service = TenantConfigurationService(
            db_manager=state.db_manager,
            tenant_key=current_user.tenant_key,
        )
        is_healthy = await config_service.execute_health_check()

        if is_healthy:
            return SuccessResponse(message="Database connection successful")
        raise HTTPException(status_code=503, detail="Database health check failed")

    except (RuntimeError, OSError, ValueError) as e:
        logger.error("Database connection failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Database connection failed. Check server logs.") from e
