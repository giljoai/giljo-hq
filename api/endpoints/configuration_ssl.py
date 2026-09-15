# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import ssl
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from giljo_mcp.auth.dependencies import require_admin, require_ce_mode
from giljo_mcp.models import User


router = APIRouter()


class SSLToggleRequest(BaseModel):
    enabled: bool = Field(..., description="Enable or disable SSL")


class SSLCertPathRequest(BaseModel):
    cert_path: str = Field(..., description="Absolute path to the PEM certificate on the server")
    key_path: str = Field(..., description="Absolute path to the PEM private key on the server")


class SSLStatusResponse(BaseModel):
    ssl_enabled: bool
    has_certificate: bool
    cert_path: str | None = None
    key_path: str | None = None
    restart_required: bool = True
    message: str
    cert_not_after: str | None = None
    cert_sans: list[str] = Field(default_factory=list)
    cert_expired: bool = False


_CERTS_DIR = "certs"
_MAX_PEM_BYTES = 64 * 1024


def _validate_cert_pair(cert_path: str, key_path: str) -> None:
    if not (Path(cert_path).exists() and Path(key_path).exists()):
        raise HTTPException(
            status_code=400,
            detail="Certificate or key file not found at the given path.",
        )
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    except (ssl.SSLError, ValueError, OSError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid certificate/key pair (must be matching PEM cert + key): {e}",
        ) from e


def _ssl_status_from_config() -> tuple[bool, str | None, str | None, bool]:
    from giljo_mcp._config_io import read_config

    config = read_config()
    ssl_enabled = config.get("features", {}).get("ssl_enabled", False)
    cert_path = config.get("paths", {}).get("ssl_cert")
    key_path = config.get("paths", {}).get("ssl_key")
    has_cert = bool(cert_path and key_path and Path(cert_path).exists() and Path(key_path).exists())
    return ssl_enabled, cert_path, key_path, has_cert


def _read_cert_details(cert_path: str) -> tuple[str | None, list[str], bool]:
    try:
        from datetime import UTC, datetime

        from cryptography import x509

        cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
        not_after = cert.not_valid_after_utc
        sans: list[str] = []
        try:
            san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            sans = [str(name.value) for name in san_ext]
        except x509.ExtensionNotFound:
            pass
        return not_after.date().isoformat(), sans, not_after < datetime.now(UTC)
    except Exception:  # noqa: BLE001 - best-effort cert read; any failure degrades to no-detail
        return None, [], False


def _write_cert_paths_to_config(cert_path: str, key_path: str) -> None:
    from giljo_mcp._config_io import read_config, write_config

    config = read_config()
    config.setdefault("paths", {})
    config["paths"]["ssl_cert"] = cert_path
    config["paths"]["ssl_key"] = key_path
    write_config(config)


@router.get("/ssl", response_model=SSLStatusResponse)
async def get_ssl_status(
    current_user: User = Depends(require_admin),
    _ce: None = Depends(require_ce_mode),
):
    """Get current SSL/HTTPS configuration status (server-level, from config.yaml)."""
    ssl_enabled, cert_path, key_path, has_cert = _ssl_status_from_config()

    not_after, sans, expired = _read_cert_details(cert_path) if has_cert else (None, [], False)

    return SSLStatusResponse(
        ssl_enabled=ssl_enabled,
        has_certificate=has_cert,
        cert_path=cert_path if has_cert else None,
        key_path=key_path if has_cert else None,
        restart_required=False,
        message="HTTPS is enabled" if ssl_enabled else "HTTPS is disabled",
        cert_not_after=not_after,
        cert_sans=sans,
        cert_expired=expired,
    )


@router.post("/ssl/cert/upload", response_model=SSLStatusResponse)
async def upload_ssl_cert(
    cert_file: UploadFile = File(..., description="PEM certificate (or full chain)"),
    key_file: UploadFile = File(..., description="PEM private key"),
    current_user: User = Depends(require_admin),
    _ce: None = Depends(require_ce_mode),
):
    """Upload a PEM certificate + key (bring-your-own-cert). INF-6236.

    The server stores the pair in its cert dir and points config.yaml at them. It
    does NOT mint or trust-validate certificates — provide a cert trusted by your
    browsers/AI agents (mkcert local CA, Let's Encrypt, or a corporate/internal CA).
    Enable HTTPS via POST /ssl afterwards (a restart applies it).
    """
    cert_bytes = await cert_file.read()
    key_bytes = await key_file.read()
    if len(cert_bytes) > _MAX_PEM_BYTES or len(key_bytes) > _MAX_PEM_BYTES:
        raise HTTPException(status_code=400, detail="Certificate or key file too large (max 64 KB).")

    certs_dir = Path.cwd() / _CERTS_DIR
    certs_dir.mkdir(parents=True, exist_ok=True)
    cert_dest = certs_dir / "ssl_cert.pem"
    key_dest = certs_dir / "ssl_key.pem"
    cert_dest.write_bytes(cert_bytes)
    key_dest.write_bytes(key_bytes)
    key_dest.chmod(0o600)

    try:
        _validate_cert_pair(str(cert_dest), str(key_dest))
    except HTTPException:
        cert_dest.unlink(missing_ok=True)
        key_dest.unlink(missing_ok=True)
        raise

    cert_abs = str(cert_dest.absolute())
    key_abs = str(key_dest.absolute())
    _write_cert_paths_to_config(cert_abs, key_abs)

    ssl_enabled, _, _, _ = _ssl_status_from_config()
    return SSLStatusResponse(
        ssl_enabled=ssl_enabled,
        has_certificate=True,
        cert_path=cert_abs,
        key_path=key_abs,
        restart_required=False,
        message="Certificate uploaded. Enable HTTPS to apply (a server restart is required).",
    )


@router.post("/ssl/cert/reference", response_model=SSLStatusResponse)
async def reference_ssl_cert(
    request_body: SSLCertPathRequest,
    current_user: User = Depends(require_admin),
    _ce: None = Depends(require_ce_mode),
):
    """Reference an existing cert+key by absolute PATH on the server (IT-managed certs).

    For operators whose certificates are provisioned/rotated out-of-band (e.g. a
    corporate PKI dropping renewed PEM files on disk). The server validates the
    pair parses + matches, then points config.yaml at the paths. No minting, no
    trust validation (client-side concern). Enable HTTPS via POST /ssl afterwards.
    """
    _validate_cert_pair(request_body.cert_path, request_body.key_path)
    _write_cert_paths_to_config(request_body.cert_path, request_body.key_path)

    ssl_enabled, _, _, _ = _ssl_status_from_config()
    return SSLStatusResponse(
        ssl_enabled=ssl_enabled,
        has_certificate=True,
        cert_path=request_body.cert_path,
        key_path=request_body.key_path,
        restart_required=False,
        message="Certificate path referenced. Enable HTTPS to apply (a server restart is required).",
    )


@router.post("/ssl", response_model=SSLStatusResponse)
async def toggle_ssl(
    request_body: SSLToggleRequest,
    current_user: User = Depends(require_admin),
    _ce: None = Depends(require_ce_mode),
):
    """Enable or disable HTTPS. INF-6236: bring-your-own-cert — no auto-minting.

    Enabling requires a cert already provisioned (POST /ssl/cert/upload or
    /ssl/cert/reference). The server is cert-agnostic; it will not generate a
    certificate for you. Writes config.yaml only (server-level, not per-tenant) —
    the same source of truth uvicorn reads at startup.
    """
    from giljo_mcp._config_io import read_config, write_config

    _, cert_path, key_path, has_cert = _ssl_status_from_config()

    if request_body.enabled and not has_cert:
        raise HTTPException(
            status_code=400,
            detail=(
                "No certificate provisioned. Upload a cert+key (PEM) or reference them by "
                "path before enabling HTTPS. GiljoAI does not mint certificates — bring your "
                "own (mkcert local CA, Let's Encrypt, or a corporate/internal CA) and make sure "
                "it is trusted by your browsers and AI coding agents."
            ),
        )
    if request_body.enabled and has_cert:
        _validate_cert_pair(cert_path, key_path)

    config = read_config()
    config.setdefault("features", {})
    config["features"]["ssl_enabled"] = request_body.enabled
    write_config(config)

    ssl_status = "enabled" if request_body.enabled else "disabled"
    return SSLStatusResponse(
        ssl_enabled=request_body.enabled,
        has_certificate=has_cert,
        cert_path=cert_path if has_cert else None,
        key_path=key_path if has_cert else None,
        restart_required=True,
        message=f"HTTPS {ssl_status}. Server restart required for changes to take effect.",
    )
