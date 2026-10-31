# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import and_, delete, exists, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models.oauth import OAuthLogin, OAuthLoginIp, OAuthRefreshToken
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


MAX_IPS_PER_LOGIN = 10
RETENTION_DAYS = 90
USE_WRITE_INTERVAL_SECONDS = 60

_NAME_CAP = 200
_UA_CAP = 256
_MCP_CLIENT_CAP = 128
_MCP_VERSION_CAP = 64


@dataclass(frozen=True)
class ConnectedApp:

    id: str
    client_id: str
    client_name: str
    connected_at: datetime
    last_used_at: datetime | None
    last_ip: str | None
    last_user_agent: str | None
    mcp_client_name: str | None
    mcp_client_version: str | None
    last_product_name: str | None
    recent_ips: list[str]


def _cap(value: str | None, limit: int) -> str | None:
    return value[:limit] if value else None


def _live_family(tenant_key: str):
    return exists().where(
        OAuthRefreshToken.family_id == OAuthLogin.family_id,
        OAuthRefreshToken.tenant_key == tenant_key,
        OAuthRefreshToken.revoked.is_(False),
    )


async def family_is_live(db: AsyncSession, *, tenant_key: str, family_id: str) -> bool:
    result = await db.execute(
        select(
            exists().where(
                OAuthRefreshToken.family_id == family_id,
                OAuthRefreshToken.tenant_key == tenant_key,
                OAuthRefreshToken.revoked.is_(False),
            )
        )
    )
    return bool(result.scalar())


async def ensure_login(
    db: AsyncSession,
    *,
    family_id: str,
    tenant_key: str,
    user_id: str,
    client_id: str,
    client_name: str,
) -> None:
    await db.execute(
        pg_insert(OAuthLogin)
        .values(
            family_id=family_id,
            tenant_key=tenant_key,
            user_id=user_id,
            client_id=client_id,
            client_name=client_name[:_NAME_CAP] or client_id[:_NAME_CAP],
        )
        .on_conflict_do_nothing(index_elements=["family_id"])
    )
    await db.execute(
        delete(OAuthLogin).where(
            OAuthLogin.tenant_key == tenant_key,
            OAuthLogin.user_id == user_id,
            func.coalesce(OAuthLogin.last_used_at, OAuthLogin.connected_at)
            < func.now() - text(f"interval '{RETENTION_DAYS} days'"),
        )
    )
    await db.flush()


async def record_use(
    db: AsyncSession,
    *,
    tenant_key: str,
    family_id: str,
    ip: str,
    user_agent: str | None,
    mcp_client_name: str | None,
    mcp_client_version: str | None = None,
) -> bool:
    result = await db.execute(
        select(OAuthLogin.id).where(OAuthLogin.family_id == family_id, OAuthLogin.tenant_key == tenant_key)
    )
    if result.scalar_one_or_none() is None:
        return False
    updated = await db.execute(
        OAuthLogin.__table__.update()
        .where(
            OAuthLogin.family_id == family_id,
            OAuthLogin.tenant_key == tenant_key,
            (OAuthLogin.last_used_at.is_(None))
            | (OAuthLogin.last_used_at < func.now() - text(f"interval '{USE_WRITE_INTERVAL_SECONDS} seconds'"))
            | (OAuthLogin.last_ip.is_distinct_from(ip)),
        )
        .values(
            last_used_at=func.now(),
            last_ip=ip,
            last_user_agent=_cap(user_agent, _UA_CAP),
            last_mcp_client_name=_cap(mcp_client_name, _MCP_CLIENT_CAP),
            last_mcp_client_version=_cap(mcp_client_version, _MCP_VERSION_CAP),
        )
        .returning(OAuthLogin.id)
    )
    login_id = updated.scalar_one_or_none()
    if login_id is None:
        return False
    await _record_ip(db, tenant_key=tenant_key, login_id=login_id, ip=ip)
    await db.flush()
    return True


async def record_product_touch(
    db: AsyncSession,
    *,
    tenant_key: str,
    family_id: str,
    product_id: str | None,
    project_id: str | None,
) -> None:
    if product_id:
        resolved = select(Product.id).where(Product.id == product_id, Product.tenant_key == tenant_key)
    elif project_id:
        resolved = select(Project.product_id).where(Project.id == project_id, Project.tenant_key == tenant_key)
    else:
        return
    await db.execute(
        OAuthLogin.__table__.update()
        .where(OAuthLogin.family_id == family_id, OAuthLogin.tenant_key == tenant_key, resolved.exists())
        .values(last_product_id=resolved.scalar_subquery())
    )


async def _record_ip(db: AsyncSession, *, tenant_key: str, login_id: str, ip: str) -> None:
    await db.execute(
        pg_insert(OAuthLoginIp)
        .values(login_id=login_id, tenant_key=tenant_key, ip_address=ip)
        .on_conflict_do_update(
            constraint="uq_oauth_login_ip",
            set_={"last_seen": func.now(), "request_count": OAuthLoginIp.request_count + 1},
        )
    )
    await db.execute(
        delete(OAuthLoginIp).where(
            OAuthLoginIp.login_id == login_id,
            OAuthLoginIp.tenant_key == tenant_key,
            OAuthLoginIp.last_seen < func.now() - text(f"interval '{RETENTION_DAYS} days'"),
        )
    )
    newest = (
        select(OAuthLoginIp.id)
        .where(OAuthLoginIp.login_id == login_id, OAuthLoginIp.tenant_key == tenant_key)
        .order_by(OAuthLoginIp.last_seen.desc(), OAuthLoginIp.id)
        .limit(MAX_IPS_PER_LOGIN)
    )
    await db.execute(
        delete(OAuthLoginIp).where(
            OAuthLoginIp.login_id == login_id,
            OAuthLoginIp.tenant_key == tenant_key,
            OAuthLoginIp.id.not_in(newest),
        )
    )


async def list_connected_apps(db: AsyncSession, *, tenant_key: str, user_id: str) -> list[ConnectedApp]:
    result = await db.execute(
        select(OAuthLogin)
        .where(
            and_(
                OAuthLogin.tenant_key == tenant_key,
                OAuthLogin.user_id == user_id,
                _live_family(tenant_key),
            )
        )
        .order_by(func.coalesce(OAuthLogin.last_used_at, OAuthLogin.connected_at).desc())
    )
    logins = list(result.scalars().all())
    if not logins:
        return []
    ip_rows = await db.execute(
        select(OAuthLoginIp.login_id, OAuthLoginIp.ip_address)
        .where(
            OAuthLoginIp.tenant_key == tenant_key,
            OAuthLoginIp.login_id.in_([login.id for login in logins]),
        )
        .order_by(OAuthLoginIp.last_seen.desc())
    )
    ips: dict[str, list[str]] = {}
    for login_id, address in ip_rows.all():
        ips.setdefault(login_id, []).append(address)
    product_names = await _product_names(db, tenant_key, {login.last_product_id for login in logins})
    return [
        ConnectedApp(
            id=login.id,
            client_id=login.client_id,
            client_name=login.client_name,
            connected_at=login.connected_at,
            last_used_at=login.last_used_at,
            last_ip=login.last_ip,
            last_user_agent=login.last_user_agent,
            mcp_client_name=login.last_mcp_client_name,
            mcp_client_version=login.last_mcp_client_version,
            last_product_name=product_names.get(login.last_product_id),
            recent_ips=ips.get(login.id, []),
        )
        for login in logins
    ]


async def _product_names(db: AsyncSession, tenant_key: str, product_ids: set[str | None]) -> dict[str, str]:
    ids = [pid for pid in product_ids if pid]
    if not ids:
        return {}
    rows = await db.execute(
        select(Product.id, Product.name).where(Product.tenant_key == tenant_key, Product.id.in_(ids))
    )
    return dict(rows.all())


async def log_out_app(db: AsyncSession, *, tenant_key: str, user_id: str, login_id: str) -> None:
    result = await db.execute(
        select(OAuthLogin.family_id).where(
            OAuthLogin.id == login_id,
            OAuthLogin.tenant_key == tenant_key,
            OAuthLogin.user_id == user_id,
        )
    )
    family_id = result.scalar_one_or_none()
    if family_id is None:
        raise ResourceNotFoundError("Connected app not found", context={"login_id": login_id})
    from giljo_mcp.services import oauth_refresh_service as _refresh

    await _refresh.revoke_family(db, family_id=str(family_id), tenant_key=tenant_key)


async def log_out_all_apps(db: AsyncSession, *, tenant_key: str, user_id: str) -> int:
    from giljo_mcp.services import oauth_refresh_service as _refresh

    return await _refresh.revoke_all_for_user(db, user_id=user_id, tenant_key=tenant_key)
