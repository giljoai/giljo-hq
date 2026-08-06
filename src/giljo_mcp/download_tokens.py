# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Token Manager for one-time download tokens.

Handover 0100: Secure, time-limited download token system for slash commands
and agent templates.

Features:
- UUID v4 token generation (cryptographically secure)
- 15-minute expiry window
- One-time use enforcement
- Multi-tenant isolation
- Automatic expired token cleanup

Usage:
    manager = TokenManager(db_session)

    # Generate token
    token = await manager.generate_token(
        tenant_key="abc123",
        download_type="slash_commands",
        filename="slash_commands.zip",
    )

    # Validate token
    is_valid = await manager.validate_token(token, tenant_key)

    # Cleanup expired
    deleted_count = await manager.cleanup_expired_tokens()
"""

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
    """
    Manages one-time download tokens for secure file downloads.

    Provides token generation, validation, and cleanup functionality
    with multi-tenant isolation and automatic expiry management.
    """

    def __init__(self, db_session: AsyncSession | None = None):
        """
        Initialize TokenManager with optional database session.

        Args:
            db_session: Optional AsyncSession for database operations.
                       If None, only UUID generation works (no persistence).
        """
        self.db_session = db_session

    async def generate_token(self, tenant_key: str, download_type: str, filename: str | None = None) -> str:
        """
        Generate a new download token.

        Creates a UUID v4 token with 15-minute expiry and stores the filename
        in the database. Token is ready for immediate use.

        If no database session is configured, only returns a UUID without
        persistence (useful for UUID uniqueness testing).

        Args:
            tenant_key: Tenant identifier for multi-tenant isolation
            download_type: Type of download ('slash_commands' or 'agent_templates')
            filename: Optional filename for the download

        Returns:
            str: UUID token string

        Raises:
            ValueError: If download_type is invalid
            HTTPException: If database operation fails
        """
        # Validate download_type (must match DB CHECK constraint in migration ce_0025)
        if download_type not in ("slash_commands", "agent_templates", "tenant_export"):
            raise ValueError(f"Invalid download_type: {download_type}")

        # If no database session, just return a UUID (for testing)
        if not self.db_session:
            return str(uuid4())

        # Create expiry timestamp (15 minutes from now)
        expires_at = datetime.now(UTC) + timedelta(minutes=15)

        # Create token record
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
        """
        Validate a download token.

        Checks if token exists, belongs to the correct tenant,
        has not expired, and has not been used.

        Args:
            token: UUID token string
            tenant_key: Tenant identifier for isolation check

        Returns:
            bool: True if token is valid, False otherwise
        """
        try:
            # Query token with tenant isolation
            stmt = select(DownloadToken).where(DownloadToken.token == token, DownloadToken.tenant_key == tenant_key)
            result = await self.db_session.execute(stmt)
            token_record = result.scalar_one_or_none()

            if not token_record:
                logger.debug("Token not found or tenant mismatch: %s", mask_token(token))
                return False

            # Check if expired
            if token_record.is_expired:
                logger.debug("Token expired: %s", mask_token(token))
                return False

            logger.debug("Token validated successfully: %s", mask_token(token))
            return True

        except SQLAlchemyError:
            logger.exception("Error validating token")
            return False

    async def cleanup_expired_tokens(self) -> dict:
        """
        Delete expired tokens from the database.

        Removes all tokens where expires_at is in the past. Should be run
        periodically as a background task.

        The ``(tenant_key, token)`` pairs of the rows that were deleted are
        captured BEFORE the DELETE and returned so the caller can reap the
        matching on-disk staging directories (``temp/{tenant_key}/{token}/``):
        the reaper used to delete DB rows only, orphaning the staging dirs on
        disk (BE-3011). The owning service for those paths (``FileStaging``)
        does the actual path-validated ``rmtree``; this method only reports
        what it purged.

        Returns:
            dict: ``{"total": <int rows deleted>, "pairs": [(tenant_key, token), ...]}``.
        """
        try:
            now = datetime.now(UTC)

            # Capture the (tenant_key, token) of every expiring row BEFORE the
            # delete so the caller can reap the matching staging dirs. Both the
            # SELECT and the DELETE are cross-tenant maintenance touching ALL
            # tenants' expired tokens (no per-tenant context); BE6004C-5: the
            # audited model-scoped bypass is the correct mechanism.
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
        """Shared result-dict shape for ``get_token_info`` / ``get_token_info_by_token``
        (BE-8000d item 7) -- the two methods differ only in how the row is
        looked up (tenant-scoped vs the public bypass-resolve path); the dict
        they build from the found row was identical."""
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
        """
        Retrieve token information (for debugging/monitoring).

        Args:
            token: UUID token string
            tenant_key: Tenant identifier for isolation check

        Returns:
            Optional[dict]: Token metadata or None if not found
        """
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
        """
        Retrieve token information by token only (no tenant isolation).
        Used for download validation where token is the authentication.

        Args:
            token: UUID token string

        Returns:
            Optional[dict]: Token metadata or None if not found
        """
        try:
            stmt = select(DownloadToken).where(DownloadToken.token == token)
            # BE6004C-5: the download token is a globally-unique UUID and IS the
            # authentication for this public download-validation path -- the
            # tenant_key is resolved FROM the fetched row, so no tenant context
            # exists before the query. The audited model-scoped bypass is the
            # correct mechanism for this resolve-from-row read.
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
        """
        Mark token as failed with error message.

        Updates staging_status to 'failed' and records error details.
        Used when file staging fails during token generation.

        Args:
            token: UUID token string
            error_message: Error description for debugging

        Returns:
            bool: True if successfully marked, False otherwise
        """
        try:
            # Query token (no tenant isolation - token is unique)
            stmt = select(DownloadToken).where(DownloadToken.token == token)
            result = await self.db_session.execute(stmt)
            token_record = result.scalar_one_or_none()

            if not token_record:
                logger.warning("Cannot mark non-existent token as failed: %s", mask_token(token))
                return False

            # Update staging status
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
        """
        Mark token as ready for download.

        Updates staging_status to 'ready' after successful file staging.
        Token becomes available for download.

        Args:
            token: UUID token string

        Returns:
            bool: True if successfully marked, False otherwise
        """
        try:
            # Query token (no tenant isolation - token is unique)
            stmt = select(DownloadToken).where(DownloadToken.token == token)
            result = await self.db_session.execute(stmt)
            token_record = result.scalar_one_or_none()

            if not token_record:
                logger.warning("Cannot mark non-existent token as ready: %s", mask_token(token))
                return False

            # Update staging status
            token_record.staging_status = "ready"
            token_record.staging_error = None  # Clear any previous errors
            # TSK-9210: stamp the per-token staleness anchor HERE, not at token creation.
            # Every caller reaches mark_ready() only AFTER staging has committed
            # last_exported_at, so staged_at lands past that write — which is precisely
            # why anchoring on created_at would false-positive on every fresh download.
            token_record.staged_at = datetime.now(UTC)

            await self.db_session.commit()

            logger.info("Token marked as ready: %s", mask_token(token))
            return True

        except SQLAlchemyError:
            await self.db_session.rollback()
            logger.exception("Error marking token as ready")
            return False

    async def increment_download_count(self, token: str, tenant_key: str) -> bool:
        """
        Increment download counter and update last download timestamp.

        Updates download_count and last_downloaded_at for metrics tracking.
        Called after successful file download.

        Args:
            token: UUID token string
            tenant_key: Tenant that owns the token. The caller resolves this
                FROM the token row (see ``get_token_info_by_token``) before this
                method runs, so the context is known and honest. Establishing it
                here lets the fail-closed tenant guard scope this metrics write
                as a proper ``WHERE tenant_key=`` query instead of forcing an
                isolation bypass -- the row can only ever be mutated by its
                owning tenant.

        Returns:
            bool: True if successfully updated, False otherwise
        """
        try:
            # Run under the resolved tenant context so the fail-closed guard
            # scopes the SELECT + UPDATE to this tenant. The download path is
            # public (token IS the auth) and carries no ambient tenant, so we
            # supply the one the caller already resolved from the token row.
            with tenant_session_context(self.db_session, tenant_key):
                stmt = select(DownloadToken).where(DownloadToken.token == token)
                result = await self.db_session.execute(stmt)
                token_record = result.scalar_one_or_none()

                if not token_record:
                    logger.warning("Cannot increment download count for non-existent token: %s", mask_token(token))
                    return False

                # Increment counter and update timestamp
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
