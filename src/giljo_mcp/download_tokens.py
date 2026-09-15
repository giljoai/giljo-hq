# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .database import tenant_isolation_bypass, tenant_session_context
from .models import DownloadToken
from .utils.log_sanitizer import mask_token, sanitize


logger = logging.getLogger(__name__)


class TokenManager:

    def __init__(self, db_session: AsyncSession | None = None):
        self.db_session = db_session

    async def generate_token(self, tenant_key: str, download_type: str, filename: str | None = None) -> str:
        if download_type not in ("slash_commands", "agent_templates", "tenant_export"):
            raise ValueError(f"Invalid download_type: {download_type}")

        if not self.db_session:
            return str(uuid4())

        expires_at = datetime.now(UTC) + timedelta(minutes=15)

        token_record = DownloadToken(
            tenant_key=tenant_key, download_type=download_type, filename=filename, expires_at=expires_at
        )

        try:
            self.db_session.add(token_record)
            await self.db_session.commit()
            await self.db_session.refresh(token_record)

            logger.info(
                "Generated download token for tenant %s, type: %s, expires: %s",
                sanitize(tenant_key),
                sanitize(download_type),
                expires_at,
            )

            return token_record.token

        except SQLAlchemyError as e:
            await self.db_session.rollback()
            logger.exception("Failed to generate download token")
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate download token"
            ) from e

    async def validate_token(self, token: str, tenant_key: str) -> bool:
        try:
            stmt = select(DownloadToken).where(DownloadToken.token == token, DownloadToken.tenant_key == tenant_key)
            result = await self.db_session.execute(stmt)
            token_record = result.scalar_one_or_none()

            if not token_record:
                logger.debug("Token not found or tenant mismatch: %s", mask_token(token))
                return False

            if token_record.is_expired:
                logger.debug("Token expired: %s", mask_token(token))
                return False

            logger.debug("Token validated successfully: %s", mask_token(token))
            return True

        except SQLAlchemyError:
            logger.exception("Error validating token")
            return False

    async def cleanup_expired_tokens(self) -> dict:
        try:
            now = datetime.now(UTC)

            select_stmt = select(DownloadToken.tenant_key, DownloadToken.token).where(DownloadToken.expires_at < now)
            delete_stmt = delete(DownloadToken).where(DownloadToken.expires_at < now)
            with tenant_isolation_bypass(
                self.db_session,
                reason="cross-tenant maintenance scan: purge expired download tokens",
                models=(DownloadToken,),
            ):
                rows = (await self.db_session.execute(select_stmt)).all()
                result = await self.db_session.execute(delete_stmt)
            await self.db_session.commit()

            deleted_count = result.rowcount
            pairs = [(row.tenant_key, row.token) for row in rows]

            if deleted_count > 0:
                logger.info("Cleaned up %d expired download tokens", deleted_count)

            return {"total": deleted_count, "pairs": pairs}

        except SQLAlchemyError:
            await self.db_session.rollback()
            logger.exception("Error cleaning up expired tokens")
            return {"total": 0, "pairs": []}

    @staticmethod
    def _serialize_token_info(token_record: DownloadToken) -> dict:
        return {
            "token": token_record.token,
            "tenant_key": token_record.tenant_key,
            "download_type": token_record.download_type,
            "filename": token_record.filename,
            "is_expired": token_record.is_expired,
            "staging_status": token_record.staging_status,
            "staging_error": token_record.staging_error,
            "download_count": token_record.download_count,
            "created_at": token_record.created_at.isoformat(),
            "expires_at": token_record.expires_at.isoformat(),
            "last_downloaded_at": token_record.last_downloaded_at.isoformat()
            if token_record.last_downloaded_at
            else None,
        }

    async def get_token_info(self, token: str, tenant_key: str) -> dict | None:
        try:
            stmt = select(DownloadToken).where(DownloadToken.token == token, DownloadToken.tenant_key == tenant_key)
            result = await self.db_session.execute(stmt)
            token_record = result.scalar_one_or_none()

            if not token_record:
                return None

            return self._serialize_token_info(token_record)

        except SQLAlchemyError:
            logger.exception("Error retrieving token info")
            return None

    async def get_token_info_by_token(self, token: str) -> dict | None:
        try:
            stmt = select(DownloadToken).where(DownloadToken.token == token)
            with tenant_isolation_bypass(
                self.db_session,
                reason="public download validation: resolve token before tenant is known",
                models=(DownloadToken,),
            ):
                result = await self.db_session.execute(stmt)
                token_record = result.scalar_one_or_none()

            if not token_record:
                return None

            return self._serialize_token_info(token_record)

        except SQLAlchemyError:
            logger.exception("Error retrieving token info")
            return None

    async def mark_failed(self, token: str, error_message: str) -> bool:
        try:
            stmt = select(DownloadToken).where(DownloadToken.token == token)
            result = await self.db_session.execute(stmt)
            token_record = result.scalar_one_or_none()

            if not token_record:
                logger.warning("Cannot mark non-existent token as failed: %s", mask_token(token))
                return False

            token_record.staging_status = "failed"
            token_record.staging_error = error_message

            await self.db_session.commit()

            logger.info("Token marked as failed: %s, error: %s", mask_token(token), sanitize(error_message))
            return True

        except SQLAlchemyError:
            await self.db_session.rollback()
            logger.exception("Error marking token as failed")
            return False

    async def mark_ready(self, token: str) -> bool:
        try:
            stmt = select(DownloadToken).where(DownloadToken.token == token)
            result = await self.db_session.execute(stmt)
            token_record = result.scalar_one_or_none()

            if not token_record:
                logger.warning("Cannot mark non-existent token as ready: %s", mask_token(token))
                return False

            token_record.staging_status = "ready"
            token_record.staging_error = None
            token_record.staged_at = datetime.now(UTC)

            await self.db_session.commit()

            logger.info("Token marked as ready: %s", mask_token(token))
            return True

        except SQLAlchemyError:
            await self.db_session.rollback()
            logger.exception("Error marking token as ready")
            return False

    async def increment_download_count(self, token: str, tenant_key: str) -> bool:
        try:
            with tenant_session_context(self.db_session, tenant_key):
                stmt = select(DownloadToken).where(DownloadToken.token == token)
                result = await self.db_session.execute(stmt)
                token_record = result.scalar_one_or_none()

                if not token_record:
                    logger.warning("Cannot increment download count for non-existent token: %s", mask_token(token))
                    return False

                token_record.download_count += 1
                token_record.last_downloaded_at = datetime.now(UTC)

                await self.db_session.commit()

            logger.info(
                "Download count incremented for token: %s, new count: %d",
                mask_token(token),
                token_record.download_count,
            )
            return True

        except SQLAlchemyError:
            await self.db_session.rollback()
            logger.exception("Error incrementing download count")
            return False
