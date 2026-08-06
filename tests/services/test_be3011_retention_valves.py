# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-3011 retention-valve regression tests (Edition Scope: Both).

Covers the three shipped retention valves at the layer each fix lives in:

1. **temp/ staging-dir leak** — the download-token reaper used to delete DB
   rows only, orphaning ``temp/{tenant_key}/{token}/`` on disk.
   - ``TokenManager.cleanup_expired_tokens`` now returns the purged
     ``(tenant_key, token)`` pairs (DB layer).
   - ``FileStaging.purge_token_dir`` does the path-validated ``rmtree``
     (service layer) — the SECURITY-CRITICAL half: it must NEVER delete
     outside the staging root (``..`` / absolute seed / symlink escape).
   - Two-sided: expired dirs are removed AND unexpired/active dirs survive;
     running it twice / on a missing dir is a safe no-op (CE installer rerun).

2. **notifications purge** — ``NotificationService.purge_resolved_older_than``
   removes only SAFELY-purgeable rows (resolved/expired past retention), is
   tenant-isolated (tenant A's purge never touches tenant B), and never deletes
   active/unresolved rows by age alone.

3. **dead mcp_session cleanup** — ``MCPSessionManager.cleanup_expired_sessions``
   was wired into the background loop; the cross-tenant DELETE now runs under
   the audited tenant-isolation bypass (without it the fail-closed guard raised
   ``TenantIsolationError`` — why it never ran). Removes inactive-beyond-48h
   sessions and leaves recent ones.

Parallel-safe: TransactionalTestContext (``db_session``), ``tmp_path`` for disk,
no module-level mutable state, no test-ordering deps.
"""

import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from api.endpoints.mcp_session import MCPSessionManager
from giljo_mcp.database import tenant_isolation_bypass, tenant_session_context
from giljo_mcp.download_tokens import TokenManager
from giljo_mcp.file_staging import FileStaging
from giljo_mcp.models import DownloadToken, MCPSession
from giljo_mcp.models.notifications import Notification
from giljo_mcp.services.notification_service import NotificationService


# ---------------------------------------------------------------------------
# Item 1 — FileStaging.purge_token_dir (the SECURITY-CRITICAL path)
# ---------------------------------------------------------------------------


class TestStagingDirReaper:
    @pytest.mark.asyncio
    async def test_expired_dir_is_removed(self, tmp_path):
        """A real, in-root staging dir is removed by the reaper."""
        staging = FileStaging(base_path=tmp_path)
        target = await staging.create_staging_directory("tenant-a", "tok-expired")
        (target / "payload.zip").write_text("data")
        assert target.exists()

        assert await staging.purge_token_dir("tenant-a", "tok-expired") is True
        assert not target.exists()
        # Tenant root itself must NOT be removed (only the token dir).
        assert (tmp_path / "tenant-a").exists()

    @pytest.mark.asyncio
    async def test_unexpired_dir_is_untouched(self, tmp_path):
        """Load-bearing half: a dir we never ask to purge stays put."""
        staging = FileStaging(base_path=tmp_path)
        keep = await staging.create_staging_directory("tenant-a", "tok-active")
        purge = await staging.create_staging_directory("tenant-a", "tok-old")

        await staging.purge_token_dir("tenant-a", "tok-old")

        assert not purge.exists()
        assert keep.exists()  # active staging survives

    @pytest.mark.asyncio
    async def test_missing_dir_is_idempotent_noop(self, tmp_path):
        """Missing dir = safe no-op (CE installer reruns the reaper every boot)."""
        staging = FileStaging(base_path=tmp_path)
        # Never created, then purge twice — both succeed without error.
        assert await staging.purge_token_dir("tenant-a", "never-existed") is True
        assert await staging.purge_token_dir("tenant-a", "never-existed") is True

        target = await staging.create_staging_directory("tenant-a", "tok")
        assert await staging.purge_token_dir("tenant-a", "tok") is True
        assert not target.exists()
        # Second purge of the now-removed dir is still a safe no-op.
        assert await staging.purge_token_dir("tenant-a", "tok") is True

    @pytest.mark.asyncio
    async def test_traversal_in_components_is_refused(self, tmp_path):
        """`..`, `/`, `\\` in tenant_key or token are refused (no deletion)."""
        staging = FileStaging(base_path=tmp_path)
        # A sentinel OUTSIDE the staging root that must never be touched.
        outside = tmp_path.parent / f"outside-{uuid4().hex}"
        outside.mkdir()
        (outside / "secret.txt").write_text("do not delete")

        for tenant_key, token in [
            ("..", "tok"),
            ("tenant-a", ".."),
            ("../escape", "tok"),
            ("tenant-a", "../escape"),
            ("a/b", "tok"),
            ("tenant-a", "a\\b"),
            ("", "tok"),
            ("tenant-a", ""),
        ]:
            assert await staging.purge_token_dir(tenant_key, token) is False

        assert outside.exists()
        assert (outside / "secret.txt").exists()

    @pytest.mark.asyncio
    async def test_absolute_seed_is_refused(self, tmp_path):
        """An absolute-path seed resolves outside the root and is refused."""
        staging = FileStaging(base_path=tmp_path)
        outside = tmp_path.parent / f"abs-target-{uuid4().hex}"
        outside.mkdir()
        # An absolute string as the token contains a path separator -> refused
        # by the traversal guard before resolution even matters.
        assert await staging.purge_token_dir("tenant-a", str(outside)) is False
        assert outside.exists()

    @pytest.mark.asyncio
    @pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privilege on Windows")
    async def test_symlink_escape_is_refused(self, tmp_path):
        """A staging dir that is a symlink to outside the root is refused.

        The containment assertion resolves the real path; a symlinked token dir
        whose target lies outside the staging root must NOT be rmtree'd, and the
        real target must survive untouched.
        """
        staging = FileStaging(base_path=tmp_path)
        (tmp_path / "tenant-a").mkdir()
        outside = tmp_path.parent / f"sym-target-{uuid4().hex}"
        outside.mkdir()
        (outside / "keep.txt").write_text("must survive")

        link = tmp_path / "tenant-a" / "tok-link"
        link.symlink_to(outside, target_is_directory=True)

        assert await staging.purge_token_dir("tenant-a", "tok-link") is False
        # The symlink target and its contents must be intact.
        assert outside.exists()
        assert (outside / "keep.txt").exists()


# ---------------------------------------------------------------------------
# Item 1 — TokenManager returns purged pairs + end-to-end reap (DB + disk)
# ---------------------------------------------------------------------------


async def _add_token(session, tenant_key: str, token: str, *, expires_at: datetime) -> None:
    """Insert a DownloadToken row under the audited bypass (cross-tenant setup)."""
    row = DownloadToken(
        token=token,
        tenant_key=tenant_key,
        download_type="agent_templates",
        filename="agent_templates.zip",
        expires_at=expires_at,
    )
    with tenant_isolation_bypass(session, reason="test setup: seed download tokens", models=(DownloadToken,)):
        session.add(row)
        await session.flush()
    await session.commit()


class TestTokenReaperReturnsPairsAndReaps:
    @pytest.mark.asyncio
    async def test_cleanup_returns_only_expired_pairs(self, db_session):
        """The reaper reports the (tenant_key, token) of expired rows only."""
        now = datetime.now(UTC)
        tenant = f"t_{uuid4().hex[:8]}"
        expired_tok = f"exp_{uuid4().hex}"
        active_tok = f"act_{uuid4().hex}"

        await _add_token(db_session, tenant, expired_tok, expires_at=now - timedelta(hours=1))
        await _add_token(db_session, tenant, active_tok, expires_at=now + timedelta(hours=1))

        result = await TokenManager(db_session).cleanup_expired_tokens()

        assert isinstance(result, dict)
        pairs = result["pairs"]
        assert (tenant, expired_tok) in pairs
        assert (tenant, active_tok) not in pairs
        assert result["total"] >= 1

        # Two-sided at the DB layer: the expired row is gone, the active survives.
        with tenant_isolation_bypass(db_session, reason="test assert: read remaining tokens", models=(DownloadToken,)):
            remaining = (
                (await db_session.execute(select(DownloadToken.token).where(DownloadToken.tenant_key == tenant)))
                .scalars()
                .all()
            )
        assert active_tok in remaining
        assert expired_tok not in remaining

    @pytest.mark.asyncio
    async def test_end_to_end_reap_removes_expired_dir_keeps_active(self, db_session, tmp_path):
        """Disk-leak regression: pairs from the reaper drive a two-sided dir reap."""
        now = datetime.now(UTC)
        tenant = f"t_{uuid4().hex[:8]}"
        expired_tok = f"exp_{uuid4().hex}"
        active_tok = f"act_{uuid4().hex}"

        staging = FileStaging(base_path=tmp_path)
        expired_dir = await staging.create_staging_directory(tenant, expired_tok)
        active_dir = await staging.create_staging_directory(tenant, active_tok)
        (expired_dir / "f.zip").write_text("x")
        (active_dir / "f.zip").write_text("y")

        await _add_token(db_session, tenant, expired_tok, expires_at=now - timedelta(hours=1))
        await _add_token(db_session, tenant, active_tok, expires_at=now + timedelta(hours=1))

        # Mirror the background task: reap rows, then purge each returned pair.
        result = await TokenManager(db_session).cleanup_expired_tokens()
        for tk, tok in result["pairs"]:
            if tk == tenant:  # ignore any unrelated rows in a shared per-worker DB
                await staging.purge_token_dir(tk, tok)

        assert not expired_dir.exists()  # orphan reaped
        assert active_dir.exists()  # active staging survives (load-bearing half)


# ---------------------------------------------------------------------------
# Item 2 — notifications retention purge
# ---------------------------------------------------------------------------


async def _add_notification(
    session,
    tenant_key: str,
    *,
    created_at: datetime,
    resolved_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> str:
    """Insert a tenant-scoped (user_id NULL) Notification under the bypass."""
    nid = str(uuid4())
    row = Notification(
        id=nid,
        tenant_key=tenant_key,
        user_id=None,
        type="api_key.expiring_soon",
        severity="info",
        title="t",
        body=None,
        payload={},
        dedupe_key=f"dk-{nid}",
        created_at=created_at,
        resolved_at=resolved_at,
        expires_at=expires_at,
    )
    # Notification is registered in the tenant-isolation guard (SEC-9276), but INSERT
    # statements are not guarded (only select/update/delete) -- session.add()+flush needs
    # no bypass here.
    session.add(row)
    await session.flush()
    await session.commit()
    return nid


async def _notification_ids(session, tenant_key: str) -> set[str]:
    """Read back a tenant's Notification ids under an explicit tenant context.

    SEC-9276: this helper is called back-to-back for DIFFERENT tenants in the same
    shared ``db_session`` (e.g. tenant A then tenant B). Without an explicit
    ``tenant_session_context`` here, the session's flush-derived tenant context (set by
    the guard's after_flush listener to whichever tenant was last inserted) would be
    stale by the time this SELECT's explicit ``tenant_key == tenant_key`` predicate runs
    for a DIFFERENT tenant, and the guard correctly refuses to trust it -- exactly the
    real cross-tenant-session bug this guard exists to catch. Scoping the read to the
    right tenant here (not bypassing the guard) keeps the isolation check live.
    """
    with tenant_session_context(session, tenant_key):
        rows = (
            (await session.execute(select(Notification.id).where(Notification.tenant_key == tenant_key)))
            .scalars()
            .all()
        )
    return set(rows)


class TestNotificationRetentionPurge:
    @pytest.mark.asyncio
    async def test_purge_respects_retention_and_only_closed_rows(self, db_manager, db_session):
        """Old resolved/expired rows go; recent resolved + unresolved survive."""
        now = datetime.now(UTC)
        tenant = f"t_{uuid4().hex[:8]}"
        old = now - timedelta(days=40)
        recent = now - timedelta(days=2)

        old_resolved = await _add_notification(db_session, tenant, created_at=old, resolved_at=old)
        old_expired = await _add_notification(db_session, tenant, created_at=old, expires_at=old)
        recent_resolved = await _add_notification(db_session, tenant, created_at=recent, resolved_at=recent)
        old_unresolved = await _add_notification(db_session, tenant, created_at=old)  # active, never resolved

        service = NotificationService(db_manager=db_manager, websocket_manager=None, session=db_session)
        deleted = await service.purge_resolved_older_than(tenant, retention_days=30)

        assert deleted == 2  # only the two old + closed rows
        survivors = await _notification_ids(db_session, tenant)
        assert old_resolved not in survivors
        assert old_expired not in survivors
        assert recent_resolved in survivors  # within retention
        assert old_unresolved in survivors  # active rows never purged by age alone

    @pytest.mark.asyncio
    async def test_purge_is_tenant_isolated(self, db_manager, db_session):
        """Tenant A's purge never touches tenant B's rows."""
        now = datetime.now(UTC)
        old = now - timedelta(days=40)
        tenant_a = f"a_{uuid4().hex[:8]}"
        tenant_b = f"b_{uuid4().hex[:8]}"

        a_old = await _add_notification(db_session, tenant_a, created_at=old, resolved_at=old)
        b_old = await _add_notification(db_session, tenant_b, created_at=old, resolved_at=old)

        service = NotificationService(db_manager=db_manager, websocket_manager=None, session=db_session)
        deleted = await service.purge_resolved_older_than(tenant_a, retention_days=30)

        assert deleted == 1
        assert a_old not in await _notification_ids(db_session, tenant_a)
        # Tenant B's identically-old resolved row is untouched.
        assert b_old in await _notification_ids(db_session, tenant_b)


# ---------------------------------------------------------------------------
# Item 3 — dead mcp_session cleanup, now wired in + bypass-guarded
# ---------------------------------------------------------------------------


async def _add_mcp_session(session, tenant_key: str, *, last_accessed: datetime) -> str:
    sid = str(uuid4())
    row = MCPSession(
        id=str(uuid4()),
        session_id=sid,
        tenant_key=tenant_key,
        last_accessed=last_accessed,
    )
    with tenant_isolation_bypass(session, reason="test setup: seed mcp sessions", models=(MCPSession,)):
        session.add(row)
        await session.flush()
    await session.commit()
    return sid


class TestMCPSessionCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_removes_inactive_keeps_recent(self, db_session):
        """Inactive-beyond-48h sessions are removed; recent ones survive.

        Also proves the cross-tenant DELETE runs WITHOUT raising
        TenantIsolationError (the bypass that makes the previously-dead path
        actually run).
        """
        now = datetime.now(UTC)
        tenant = f"t_{uuid4().hex[:8]}"
        stale = await _add_mcp_session(db_session, tenant, last_accessed=now - timedelta(hours=72))
        fresh = await _add_mcp_session(db_session, tenant, last_accessed=now - timedelta(hours=1))

        removed = await MCPSessionManager(db_session).cleanup_expired_sessions()

        assert removed >= 1
        with tenant_isolation_bypass(db_session, reason="test assert: read mcp sessions", models=(MCPSession,)):
            remaining = (
                (await db_session.execute(select(MCPSession.session_id).where(MCPSession.tenant_key == tenant)))
                .scalars()
                .all()
            )
        assert fresh in remaining
        assert stale not in remaining
