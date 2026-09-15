# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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




class TestStagingDirReaper:
    @pytest.mark.asyncio
    async def test_expired_dir_is_removed(self, tmp_path):
        staging = FileStaging(base_path=tmp_path)
        target = await staging.create_staging_directory("tenant-a", "tok-expired")
        (target / "payload.zip").write_text("data")
        assert target.exists()

        assert await staging.purge_token_dir("tenant-a", "tok-expired") is True
        assert not target.exists()
        assert (tmp_path / "tenant-a").exists()

    @pytest.mark.asyncio
    async def test_unexpired_dir_is_untouched(self, tmp_path):
        staging = FileStaging(base_path=tmp_path)
        keep = await staging.create_staging_directory("tenant-a", "tok-active")
        purge = await staging.create_staging_directory("tenant-a", "tok-old")

        await staging.purge_token_dir("tenant-a", "tok-old")

        assert not purge.exists()
        assert keep.exists()

    @pytest.mark.asyncio
    async def test_missing_dir_is_idempotent_noop(self, tmp_path):
        staging = FileStaging(base_path=tmp_path)
        assert await staging.purge_token_dir("tenant-a", "never-existed") is True
        assert await staging.purge_token_dir("tenant-a", "never-existed") is True

        target = await staging.create_staging_directory("tenant-a", "tok")
        assert await staging.purge_token_dir("tenant-a", "tok") is True
        assert not target.exists()
        assert await staging.purge_token_dir("tenant-a", "tok") is True

    @pytest.mark.asyncio
    async def test_traversal_in_components_is_refused(self, tmp_path):
        staging = FileStaging(base_path=tmp_path)
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
        staging = FileStaging(base_path=tmp_path)
        outside = tmp_path.parent / f"abs-target-{uuid4().hex}"
        outside.mkdir()
        assert await staging.purge_token_dir("tenant-a", str(outside)) is False
        assert outside.exists()

    @pytest.mark.asyncio
    @pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privilege on Windows")
    async def test_symlink_escape_is_refused(self, tmp_path):
        staging = FileStaging(base_path=tmp_path)
        (tmp_path / "tenant-a").mkdir()
        outside = tmp_path.parent / f"sym-target-{uuid4().hex}"
        outside.mkdir()
        (outside / "keep.txt").write_text("must survive")

        link = tmp_path / "tenant-a" / "tok-link"
        link.symlink_to(outside, target_is_directory=True)

        assert await staging.purge_token_dir("tenant-a", "tok-link") is False
        assert outside.exists()
        assert (outside / "keep.txt").exists()




async def _add_token(session, tenant_key: str, token: str, *, expires_at: datetime) -> None:
    row = DownloadToken(
        token=token,
        tenant_key=tenant_key,
        download_type="slash_commands",
        filename="giljo_setup.zip",
        expires_at=expires_at,
    )
    with tenant_isolation_bypass(session, reason="test setup: seed download tokens", models=(DownloadToken,)):
        session.add(row)
        await session.flush()
    await session.commit()


class TestTokenReaperReturnsPairsAndReaps:
    @pytest.mark.asyncio
    async def test_cleanup_returns_only_expired_pairs(self, db_session):
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

        result = await TokenManager(db_session).cleanup_expired_tokens()
        for tk, tok in result["pairs"]:
            if tk == tenant:
                await staging.purge_token_dir(tk, tok)

        assert not expired_dir.exists()
        assert active_dir.exists()




async def _add_notification(
    session,
    tenant_key: str,
    *,
    created_at: datetime,
    resolved_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> str:
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
    session.add(row)
    await session.flush()
    await session.commit()
    return nid


async def _notification_ids(session, tenant_key: str) -> set[str]:
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
        now = datetime.now(UTC)
        tenant = f"t_{uuid4().hex[:8]}"
        old = now - timedelta(days=40)
        recent = now - timedelta(days=2)

        old_resolved = await _add_notification(db_session, tenant, created_at=old, resolved_at=old)
        old_expired = await _add_notification(db_session, tenant, created_at=old, expires_at=old)
        recent_resolved = await _add_notification(db_session, tenant, created_at=recent, resolved_at=recent)
        old_unresolved = await _add_notification(db_session, tenant, created_at=old)

        service = NotificationService(db_manager=db_manager, websocket_manager=None, session=db_session)
        deleted = await service.purge_resolved_older_than(tenant, retention_days=30)

        assert deleted == 2
        survivors = await _notification_ids(db_session, tenant)
        assert old_resolved not in survivors
        assert old_expired not in survivors
        assert recent_resolved in survivors
        assert old_unresolved in survivors

    @pytest.mark.asyncio
    async def test_purge_is_tenant_isolated(self, db_manager, db_session):
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
        assert b_old in await _notification_ids(db_session, tenant_b)




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
