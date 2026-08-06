# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
MCP Session Management for HTTP Transport

Provides session state management for MCP-over-HTTP connections.
Enables stateful context preservation across tool calls while maintaining
multi-tenant isolation.

Architecture:
- API key authentication via X-API-Key header
- Session persistence in PostgreSQL (mcp_sessions table)
- One session row per client connection, minted at ``initialize`` (BE-9066)
- Auto-expiration after 24 hours of inactivity
- Tenant context resolution from API key -> User -> tenant_key
- Project context preservation across tool calls

Usage:
    session_manager = MCPSessionManager(db_session)
    session = await session_manager.create_session(tenant_key=tk, user_id=uid, api_key_id=kid)
    await session_manager.update_session_data(session.session_id, data)
"""

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.harness_resolver import preset_from_client_info
from giljo_mcp.models import MCPSession
from giljo_mcp.platform_registry import harness_from_client_info
from giljo_mcp.services.debounce import should_run


logger = logging.getLogger(__name__)


def _client_info_patch(client_info: dict[str, Any] | None) -> dict[str, Any]:
    """Build the session_data patch for a captured ``initialize`` clientInfo (BE-9035b).

    Stores the raw ``client_info`` (INF-8003d) AND the harness token it resolves to
    (``resolved_harness``), stamped at the same point clientInfo is persisted so a
    later tool render can read the DETECTED harness off the session record without
    re-resolving. Absent/empty/unknown clientInfo → ``"generic"`` (the fail-safe
    floor); the resolver drives RENDERING only, never auth.

    BE-9327 adds ``resolved_preset`` on the same vehicle and for the same reason: the
    harness PRESET (web_sandbox / chat) is derivable only from the initialize
    clientInfo, which ``stateless_http`` drops on every later tools/call. ``None`` for
    every client that is not an unambiguously-hosted surface. Rows written before
    BE-9327 simply lack the key; every reader uses ``.get``, so a legacy session
    resolves to no preset — exactly its behaviour today.
    """
    info = client_info or {}
    return {
        "client_info": info,
        "resolved_harness": harness_from_client_info(info.get("name"), info.get("version")),
        "resolved_preset": preset_from_client_info(info.get("name"), info.get("version")),
    }


# BE-6070 (F5): in-process debounce windows for per-call session bookkeeping.
# Each window (seconds) is MASSIVELY smaller than the session lifetime (hours),
# so debouncing an extend has zero practical effect on validity. Auth VALIDATION
# (key verify, session SELECT, tenant gating, expiry) is never debounced -- only
# the write frequency of pure bookkeeping is reduced. The FIRST write for any
# key/session always lands (check-and-set).
_LAST_USED_DEBOUNCE_SECONDS = 10  # api_keys.last_used (F5.1)
SESSION_EXTEND_DEBOUNCE_SECONDS = 30  # mcp_sessions.extend_expiration (F5.2 + F5.4)
_IP_LOG_SAMPLE_SECONDS = 60  # api_key_ip_log upsert sampling (F5.3)

# BE-6070: shared debounce namespaces. The lifecycle extend (F5.4, mcp_sdk_server)
# keys by session_id so N rapid calls on one session collapse to one write per
# window. (F5.2's per-request extend inside the old get_or_create reuse path was
# removed with that path in BE-9066 — F5.4 is now the single extend site.)
_NS_LAST_USED = "api_key_last_used"
SESSION_EXTEND_NS = "mcp_session_extend"
_NS_IP_LOG = "api_key_ip_log"

# BE-9066: the ONLY session-id shape this server ever mints (str(uuid4()), 36
# chars, lowercase). Soft-resurrection refuses anything else, so a foreign or
# oversized echoed id can never reach the String(36) INSERT and 404s exactly as
# an unknown id always has.
_MINTED_SESSION_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class MCPSessionManager:
    """Manages MCP HTTP sessions with PostgreSQL persistence"""

    DEFAULT_SESSION_LIFETIME_HOURS = 24
    SESSION_CLEANUP_THRESHOLD_HOURS = 48

    def __init__(self, db: AsyncSession):
        self.db = db

    async def authenticate_api_key(self, api_key_value: str):
        """Validate an API key and return the associated (APIKey, User) tuple.

        SEC-3004c: the prefix-narrowed, off-loop bcrypt verify + tenant/is_active
        user resolution lives in the single ``_resolve_api_key`` loop (shared
        with the REST and WebSocket transports). This method keeps only the
        MCP-transport bookkeeping (debounced ``last_used`` write) and the broad
        API-boundary catch that converts any failure to a clean ``None`` (so a
        DB fault yields 401, never a 500 leaking out of the auth boundary).
        Returns None if no key matches or the owning user is inactive / in a
        different tenant.
        """
        try:
            from giljo_mcp.auth.principal import _resolve_api_key

            resolved = await _resolve_api_key(self.db, api_key_value)
            if resolved is None:
                logger.warning("Invalid API key provided")
                return None
            key_record, user = resolved

            # BE-6070 (F5.1): last_used is bookkeeping. Debounce the UPDATE+COMMIT
            # per api_key_id so a looping agent on one key does not write it every
            # call; the first call (and after the window) still records usage.
            if should_run(_NS_LAST_USED, str(key_record.id), _LAST_USED_DEBOUNCE_SECONDS):
                key_record.last_used = datetime.now(UTC)
                await self.db.commit()  # single-writer-allow: MCP transport last_used bookkeeping (BE-6070 debounce; pre-existing exception site)
            self.db.info["tenant_key"] = key_record.tenant_key

            logger.debug(f"API key authenticated: {key_record.name} (user: {user.username})")
            return (key_record, user)

        except Exception as e:  # Broad catch: API boundary, converts to HTTP error
            logger.error(f"API key authentication error: {e}", exc_info=True)
            return None

    async def log_ip(self, api_key_id: str, ip_address: str) -> None:
        """Log IP address for API key usage tracking (passive, non-blocking).

        Uses PostgreSQL upsert (INSERT ... ON CONFLICT) to either create a new
        entry or increment the request_count for an existing api_key + ip_address
        pair.

        This method is designed to never raise exceptions. All errors are
        caught and logged as warnings so that IP logging never blocks or
        slows down the authentication flow.

        Args:
            api_key_id: The ID of the API key that was used.
            ip_address: The client IP address (IPv4/IPv6 or 'unknown').
        """
        # BE-6070 (F5.3): cap the audit upsert to ~1x/60s per (api_key_id, ip) so
        # it is not a per-call commit. A NEW (key, ip) pair always logs on first
        # contact (check-and-set); only repeat hits from the same pair within the
        # window are sampled out, so request_count is approximate by design while
        # the "which IPs used this key" audit signal stays intact.
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
        except Exception as e:  # noqa: BLE001 - API boundary: non-fatal IP logging
            logger.warning("Failed to log IP for API key: %s", e)

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
    ) -> MCPSession:
        """Mint a NEW MCP session row — one per client connection (BE-9066).

        Called only for an ``initialize`` request (or a soft-resurrection, which
        supplies the echoed ``session_id``). Per the MCP spec a session begins at
        ``initialize`` and belongs to ONE client instance, so this is an
        unconditional plain INSERT: no per-principal reuse lookup and no dedup
        delete — N concurrent clients on one login each own their row, and a
        second client's initialize can no longer overwrite the first's
        ``client_info``/``resolved_harness`` (last-writer-wins contamination)
        nor delete its sibling rows. ``client_info`` + the harness it resolves
        to are stamped at creation only. ``auth_method``/``username`` are the
        JWT path's audit fields (absent on API-key rows, matching the prior
        per-path session_data shapes).
        """
        # BE6004C enforce: callers may open a bare db session with no tenant
        # context; bind it before the INSERT or the do_orm_execute guard raises.
        self.db.info["tenant_key"] = tenant_key
        session_data: dict[str, Any] = {
            "initialized": False,
            "capabilities": {},
            **_client_info_patch(client_info),
            "tool_call_history": [],
        }
        if auth_method:
            session_data["auth_method"] = auth_method
            session_data["username"] = username

        new_session = MCPSession(
            api_key_id=api_key_id,
            user_id=user_id,  # Handover 0424: Audit trail
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

    async def resurrect_session(
        self,
        session_id: str,
        *,
        tenant_key: str,
        user_id: str | None,
        api_key_id: str | None = None,
        auth_method: str | None = None,
    ) -> MCPSession | None:
        """Soft-resurrect a well-formed session id for its authenticated caller (BE-9066).

        Never-terminate posture: this server never terminates sessions on
        protocol events (``delete_session`` has zero callers; DELETE /mcp is
        answered 405 by the stateless SDK), so a well-formed id from an
        authenticated caller is revived rather than 404'd — the availability
        hedge for clients whose auto-recovery from a session 404 is
        unconfirmed. Three branches:

        - the caller's OWN row still exists but expired (reaper hasn't swept
          it): extend it in place — the client keeps its harness identity;
        - the id is unknown: INSERT a fresh generic-harness row bound to the
          caller's principal + tenant (the client's next re-initialize replaces
          it with a properly-identified one);
        - the id exists for ANOTHER principal or tenant: the INSERT hits the
          ``session_id`` unique constraint → rollback → principal-scoped
          re-select (which also settles the concurrent same-caller resurrect
          race) → ``None``, indistinguishable from an unknown id. The
          cross-tenant 404 is preserved.

        Only ids in this server's own minted shape (canonical lowercase UUID)
        are eligible — anything else returns ``None`` exactly as an unknown id
        always has, and an oversized value never reaches the String(36) column.
        """
        if not _MINTED_SESSION_ID_RE.fullmatch(session_id):
            return None
        if api_key_id is None and user_id is None:
            return None  # no principal to bind a resurrected row to

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
        """Retrieve a session by ID, returning None if expired or not found.

        BE-9066 principal binding: when the transport supplies the
        authenticated caller's principal, the row must BELONG to it — an
        API-key caller only reaches rows minted by that exact key; a JWT caller
        only reaches key-less rows (``api_key_id IS NULL``) of that user. A
        mismatch returns ``None``, indistinguishable from an unknown id (no
        existence leak). Binding is a constraint on top of tenant scoping,
        never a substitute for it. Passing no principal keeps the plain
        tenant-scoped read (internal bookkeeping callers).
        """
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
        """True when the row was minted by the calling principal (BE-9066).

        Strict-symmetric: an API-key principal owns only rows carrying that
        exact ``api_key_id``; a JWT principal owns only key-less rows carrying
        its ``user_id``. A cross-key / cross-method echo is NOT the same
        principal even for the same human — keys are independently revocable
        credentials. No principal supplied = no binding.
        """
        if caller_api_key_id is not None:
            return session.api_key_id == caller_api_key_id
        if caller_user_id is not None:
            return session.api_key_id is None and session.user_id == caller_user_id
        return True

    async def update_session_data(
        self, session_id: str, data: dict[str, Any], merge: bool = True, tenant_key: str | None = None
    ) -> bool:
        """Update the JSON session_data blob for a session.

        When merge is True (default), new keys are merged into existing data.
        When False, the entire blob is replaced.

        Args:
            tenant_key: When provided, the lookup is scoped to this tenant
                        (recommended for multi-tenant isolation).
        """
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

    async def cleanup_expired_sessions(self) -> int:
        """Delete sessions inactive beyond SESSION_CLEANUP_THRESHOLD_HOURS.

        Cross-tenant maintenance sweep (BE-3011): sessions expire by inactivity
        regardless of tenant, and this runs from the background-task loop with
        no ambient tenant context. The DELETE touches every tenant's stale
        rows, so it must run under the audited model-scoped tenant-isolation
        bypass (mirrors ``TokenManager.cleanup_expired_tokens``); without it the
        fail-closed guard raises ``TenantIsolationError`` — which is why this
        path never actually ran before being wired in.

        Returns the number of sessions removed.
        """
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
        """Delete a specific session by ID. Returns True if a session was removed.

        Args:
            tenant_key: When provided, the DELETE is scoped to this tenant
                        (recommended for multi-tenant isolation).
        """
        stmt = delete(MCPSession).where(MCPSession.session_id == session_id)
        if tenant_key is not None:
            stmt = stmt.where(MCPSession.tenant_key == tenant_key)
        result = await self.db.execute(stmt)
        await self.db.commit()

        if result.rowcount > 0:
            logger.info(f"Deleted MCP session: {session_id}")
            return True

        return False
