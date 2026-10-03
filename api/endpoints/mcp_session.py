# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.harness_resolver import preset_from_client_info
from giljo_mcp.models import MCPSession
from giljo_mcp.platform_registry import harness_from_client_info
from giljo_mcp.services.debounce import should_run
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


def _client_info_patch(
    client_info: dict[str, Any] | None,
    protocol_version: str | None = None,
    capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    info = client_info or {}
    return {
        "client_info": info,
        "resolved_harness": harness_from_client_info(info.get("name"), info.get("version")),
        "resolved_preset": preset_from_client_info(info.get("name"), info.get("version")),
        "protocol_version": protocol_version,
        "client_capabilities": capabilities,
    }


_LAST_USED_DEBOUNCE_SECONDS = 10
SESSION_EXTEND_DEBOUNCE_SECONDS = 30
_IP_LOG_SAMPLE_SECONDS = 60

_NS_LAST_USED = "api_key_last_used"
SESSION_EXTEND_NS = "mcp_session_extend"
_NS_IP_LOG = "api_key_ip_log"

_MINTED_SESSION_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class MCPSessionManager:

    DEFAULT_SESSION_LIFETIME_HOURS = 24
    SESSION_CLEANUP_THRESHOLD_HOURS = 48

    def __init__(self, db: AsyncSession):
        self.db = db

    async def authenticate_api_key(self, api_key_value: str):
        from giljo_mcp.auth.principal import _resolve_api_key

        resolved = await _resolve_api_key(self.db, api_key_value)
        if resolved is None:
            logger.warning("Invalid API key provided")
            return None
        key_record, user = resolved

        if should_run(_NS_LAST_USED, str(key_record.id), _LAST_USED_DEBOUNCE_SECONDS):
            key_record.last_used = datetime.now(UTC)
            await self.db.commit()
        self.db.info["tenant_key"] = key_record.tenant_key

        logger.debug(f"API key authenticated: {key_record.name} (user: {user.username})")
        return (key_record, user)

    async def log_ip(self, api_key_id: str, ip_address: str) -> None:
        if not should_run(_NS_IP_LOG, f"{api_key_id}:{ip_address}", _IP_LOG_SAMPLE_SECONDS):
            return
        try:
            from uuid import uuid4

            from sqlalchemy.dialects.postgresql import insert as pg_insert

            from giljo_mcp.models.auth import ApiKeyIpLog

            stmt = (
                pg_insert(ApiKeyIpLog)
                .values(
                    id=str(uuid4()),
                    api_key_id=api_key_id,
                    ip_address=ip_address,
                )
                .on_conflict_do_update(
                    constraint="uq_api_key_ip",
                    set_={
                        "request_count": ApiKeyIpLog.request_count + 1,
                    },
                )
            )
            await self.db.execute(stmt)
            await self.db.commit()
        except SQLAlchemyError:
            await self.db.rollback()
            logger.warning("Failed to log IP for API key (non-blocking)", exc_info=True)

    async def create_session(
        self,
        *,
        tenant_key: str,
        user_id: str | None,
        api_key_id: str | None = None,
        project_id: str | None = None,
        client_info: dict[str, Any] | None = None,
        auth_method: str | None = None,
        username: str | None = None,
        session_id: str | None = None,
        protocol_version: str | None = None,
        capabilities: dict[str, Any] | None = None,
    ) -> MCPSession:
        self.db.info["tenant_key"] = tenant_key
        session_data: dict[str, Any] = {
            "initialized": False,
            "capabilities": {},
            **_client_info_patch(client_info, protocol_version, capabilities),
            "tool_call_history": [],
        }
        if auth_method:
            session_data["auth_method"] = auth_method
            session_data["username"] = username

        new_session = MCPSession(
            api_key_id=api_key_id,
            user_id=user_id,
            tenant_key=tenant_key,
            project_id=project_id,
            session_data=session_data,
            created_at=datetime.now(UTC),
            last_accessed=datetime.now(UTC),
        )
        if session_id is not None:
            new_session.session_id = session_id
        new_session.extend_expiration(self.DEFAULT_SESSION_LIFETIME_HOURS)

        self.db.add(new_session)
        await self.db.commit()
        await self.db.refresh(new_session)

        logger.info(f"Created new MCP session: {new_session.session_id} (tenant: {tenant_key})")
        return new_session

    async def touch_or_create_client_session(
        self,
        *,
        tenant_key: str,
        user_id: str | None,
        api_key_id: str | None = None,
        client_info: dict[str, Any] | None = None,
        auth_method: str | None = None,
        protocol_version: str | None = None,
        capabilities: dict[str, Any] | None = None,
    ) -> MCPSession | None:
        name = (client_info or {}).get("name")
        if not isinstance(name, str) or not name:
            return None

        self.db.info["tenant_key"] = tenant_key

        existing = (
            (
                await self.db.execute(
                    select(MCPSession).where(
                        MCPSession.tenant_key == tenant_key,
                        MCPSession.user_id == user_id,
                        MCPSession.session_data["client_info"]["name"].astext == name,
                    )
                )
            )
            .scalars()
            .first()
        )

        if existing is not None:
            patch = _client_info_patch(client_info, protocol_version, capabilities)
            await self.update_session_data(existing.session_id, patch, merge=True, tenant_key=tenant_key)
            await self.db.refresh(existing)
            return existing

        return await self.create_session(
            tenant_key=tenant_key,
            user_id=user_id,
            api_key_id=api_key_id,
            client_info=client_info,
            auth_method=auth_method,
            protocol_version=protocol_version,
            capabilities=capabilities,
        )

    async def resurrect_session(
        self,
        session_id: str,
        *,
        tenant_key: str,
        user_id: str | None,
        api_key_id: str | None = None,
        auth_method: str | None = None,
    ) -> MCPSession | None:
        if not _MINTED_SESSION_ID_RE.fullmatch(session_id):
            return None
        if api_key_id is None and user_id is None:
            return None

        self.db.info["tenant_key"] = tenant_key

        async def _owned_row() -> MCPSession | None:
            stmt = select(MCPSession).where(
                MCPSession.session_id == session_id,
                MCPSession.tenant_key == tenant_key,
            )
            if api_key_id is not None:
                stmt = stmt.where(MCPSession.api_key_id == api_key_id)
            else:
                stmt = stmt.where(MCPSession.api_key_id.is_(None), MCPSession.user_id == user_id)
            return (await self.db.execute(stmt)).scalar_one_or_none()

        row = await _owned_row()
        if row is None:
            try:
                return await self.create_session(
                    tenant_key=tenant_key,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    auth_method=auth_method,
                    session_id=session_id,
                )
            except IntegrityError:
                await self.db.rollback()
                row = await _owned_row()
                if row is None:
                    return None

        row.extend_expiration(self.DEFAULT_SESSION_LIFETIME_HOURS)
        await self.db.commit()
        await self.db.refresh(row)
        logger.info(f"Soft-resurrected MCP session: {session_id} (tenant: {tenant_key})")
        return row

    async def get_session(
        self,
        session_id: str,
        tenant_key: str | None = None,
        *,
        caller_api_key_id: str | None = None,
        caller_user_id: str | None = None,
    ) -> MCPSession | None:
        if tenant_key:
            self.db.info["tenant_key"] = tenant_key
        stmt = select(MCPSession).where(MCPSession.session_id == session_id)
        if tenant_key is not None:
            stmt = stmt.where(MCPSession.tenant_key == tenant_key)
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if session and not self._session_belongs_to_caller(session, caller_api_key_id, caller_user_id):
            logger.info("MCP session %s is not bound to the calling principal; treating as unknown", session_id)
            return None

        if session and session.is_expired:
            logger.warning(f"Session expired: {session_id}")
            return None

        return session

    @staticmethod
    def _session_belongs_to_caller(
        session: MCPSession, caller_api_key_id: str | None, caller_user_id: str | None
    ) -> bool:
        if caller_api_key_id is not None:
            return session.api_key_id == caller_api_key_id
        if caller_user_id is not None:
            return session.api_key_id is None and session.user_id == caller_user_id
        return True

    async def update_session_data(
        self, session_id: str, data: dict[str, Any], merge: bool = True, tenant_key: str | None = None
    ) -> bool:
        session = await self.get_session(session_id, tenant_key=tenant_key)
        if not session:
            return False

        if merge:
            current_data = session.session_data or {}
            current_data.update(data)
            session.session_data = current_data
        else:
            session.session_data = data

        session.last_accessed = datetime.now(UTC)
        await self.db.commit()

        logger.debug(f"Updated session data: {session_id}")
        return True

    async def delete_sessions_for_harness(self, *, tenant_key: str, harness: str) -> int:
        from giljo_mcp.platform_registry import harness_from_client_info

        self.db.info["tenant_key"] = tenant_key

        rows = (await self.db.execute(select(MCPSession).where(MCPSession.tenant_key == tenant_key))).scalars().all()

        doomed = [
            row
            for row in rows
            if harness_from_client_info(
                ((row.session_data or {}).get("client_info") or {}).get("name"),
                ((row.session_data or {}).get("client_info") or {}).get("version"),
            )
            == harness
        ]
        if not doomed:
            return 0

        for row in doomed:
            await self.db.delete(row)
        await self.db.commit()

        logger.info(
            "Removed %d MCP session row(s) for harness=%s (tenant: %s)",
            len(doomed),
            sanitize(harness),
            sanitize(tenant_key),
        )
        return len(doomed)

    async def cleanup_expired_sessions(self) -> int:
        threshold = datetime.now(UTC) - timedelta(hours=self.SESSION_CLEANUP_THRESHOLD_HOURS)

        stmt = delete(MCPSession).where(MCPSession.last_accessed < threshold)

        with tenant_isolation_bypass(
            self.db,
            reason="cross-tenant maintenance scan: purge inactive MCP sessions",
            models=(MCPSession,),
        ):
            result = await self.db.execute(stmt)
        await self.db.commit()

        count = result.rowcount
        if count > 0:
            logger.info(f"Cleaned up {count} expired MCP sessions")

        return count

    async def delete_session(self, session_id: str, tenant_key: str | None = None) -> bool:
        stmt = delete(MCPSession).where(MCPSession.session_id == session_id)
        if tenant_key is not None:
            stmt = stmt.where(MCPSession.tenant_key == tenant_key)
        result = await self.db.execute(stmt)
        await self.db.commit()

        if result.rowcount > 0:
            logger.info(f"Deleted MCP session: {session_id}")
            return True

        return False
