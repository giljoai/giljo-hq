# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from giljo_mcp.database import tenant_session_context


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

    from giljo_mcp.database import DatabaseManager


@asynccontextmanager
async def optional_tenant_session(
    db_manager: DatabaseManager,
    tenant_key: str | None,
    test_session: AsyncSession | None,
) -> AsyncIterator[AsyncSession]:
    if test_session is not None:
        if tenant_key:
            with tenant_session_context(test_session, tenant_key):
                yield test_session
        else:
            yield test_session
    else:
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            yield session


@asynccontextmanager
async def tenant_scoped_session(
    db_manager: DatabaseManager,
    tenant_key: str | None,
    test_session: AsyncSession | None,
) -> AsyncIterator[AsyncSession]:
    if test_session is not None:
        with tenant_session_context(test_session, tenant_key):
            yield test_session
    else:
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            yield session


@asynccontextmanager
async def tenant_context_session(
    db_manager: DatabaseManager,
    tenant_key: str | None,
    test_session: AsyncSession | None,
) -> AsyncIterator[AsyncSession]:
    if test_session is not None:
        with tenant_session_context(test_session, tenant_key):
            yield test_session
    else:
        async with db_manager.get_session_async() as session:
            with tenant_session_context(session, tenant_key):
                yield session
