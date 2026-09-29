# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.download_tokens import TokenManager
from giljo_mcp.exceptions import DatabaseError
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


class TestMarkReadyAndMarkFailedRaiseOnDbFailure:

    async def test_mark_ready_raises_database_error_on_commit_failure(self, db_session: AsyncSession) -> None:
        tenant_key = TenantManager.generate_tenant_key()
        manager = TokenManager(db_session)
        token = await manager.generate_token(tenant_key, "slash_commands", filename="f.zip")

        async def _boom():
            raise SQLAlchemyError("simulated commit failure")

        db_session.commit = _boom

        with pytest.raises(DatabaseError):
            await manager.mark_ready(token)

    async def test_mark_failed_raises_database_error_on_commit_failure(self, db_session: AsyncSession) -> None:
        tenant_key = TenantManager.generate_tenant_key()
        manager = TokenManager(db_session)
        token = await manager.generate_token(tenant_key, "slash_commands", filename="f.zip")

        async def _boom():
            raise SQLAlchemyError("simulated commit failure")

        db_session.commit = _boom

        with pytest.raises(DatabaseError):
            await manager.mark_failed(token, "staging blew up")

    async def test_mark_ready_still_returns_false_for_an_unknown_token(self, db_session: AsyncSession) -> None:
        tenant_key = TenantManager.generate_tenant_key()
        manager = TokenManager(db_session)
        with tenant_session_context(db_session, tenant_key):
            assert await manager.mark_ready("ghost-token") is False

    async def test_mark_failed_still_returns_false_for_an_unknown_token(self, db_session: AsyncSession) -> None:
        tenant_key = TenantManager.generate_tenant_key()
        manager = TokenManager(db_session)
        with tenant_session_context(db_session, tenant_key):
            assert await manager.mark_failed("ghost-token", "irrelevant") is False


class TestClaimDownloadEnforcesSingleUse:

    async def test_first_claim_succeeds(self, db_session: AsyncSession) -> None:
        tenant_key = TenantManager.generate_tenant_key()
        manager = TokenManager(db_session)
        token = await manager.generate_token(tenant_key, "slash_commands", filename="f.zip")

        assert await manager.claim_download(token, tenant_key) is True

        info = await manager.get_token_info(token, tenant_key)
        assert info["download_count"] == 1
        assert info["last_downloaded_at"] is not None

    async def test_second_claim_on_the_same_token_is_refused(self, db_session: AsyncSession) -> None:
        tenant_key = TenantManager.generate_tenant_key()
        manager = TokenManager(db_session)
        token = await manager.generate_token(tenant_key, "slash_commands", filename="f.zip")

        assert await manager.claim_download(token, tenant_key) is True
        assert await manager.claim_download(token, tenant_key) is False

        info = await manager.get_token_info(token, tenant_key)
        assert info["download_count"] == 1

    async def test_claim_on_unknown_token_is_refused(self, db_session: AsyncSession) -> None:
        tenant_key = TenantManager.generate_tenant_key()
        manager = TokenManager(db_session)
        assert await manager.claim_download("ghost-token", tenant_key) is False

    async def test_claim_raises_database_error_on_commit_failure(self, db_session: AsyncSession) -> None:
        tenant_key = TenantManager.generate_tenant_key()
        manager = TokenManager(db_session)
        token = await manager.generate_token(tenant_key, "slash_commands", filename="f.zip")

        async def _boom():
            raise SQLAlchemyError("simulated commit failure")

        db_session.commit = _boom

        with pytest.raises(DatabaseError):
            await manager.claim_download(token, tenant_key)
