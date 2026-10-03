# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


async def log_api_key_ip(db: AsyncSession, api_key_id: str, ip_address: str) -> None:
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
        await db.execute(stmt)
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.warning("Failed to log IP for API key (non-blocking)", exc_info=True)
