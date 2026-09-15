# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from typing import Any

from sqlalchemy import distinct, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models import Configuration
from giljo_mcp.models.auth import User


class ConfigurationRepository:

    def __init__(self, db_manager):
        self.db = db_manager


    async def list_tenant_keys(
        self,
        session: AsyncSession,
    ) -> list[str]:
        result = await session.execute(
            select(distinct(Configuration.tenant_key)).where(Configuration.tenant_key.isnot(None))
        )
        return [row[0] for row in result]

    async def get_value(
        self,
        session: AsyncSession,
        tenant_key: str,
        key: str,
    ) -> Any | None:
        stmt = select(Configuration.value).where(
            Configuration.tenant_key == tenant_key,
            Configuration.key == key,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_value(
        self,
        session: AsyncSession,
        tenant_key: str,
        key: str,
        value: Any,
        category: str = "general",
    ) -> None:
        now = datetime.now(UTC)
        stmt = pg_insert(Configuration).values(
            tenant_key=tenant_key,
            project_id=None,
            key=key,
            value=value,
            category=category,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_config_tenant_key",
            set_={"value": stmt.excluded.value, "updated_at": now},
        )
        await session.execute(stmt)

    async def get_all_values_for_key(
        self,
        session: AsyncSession,
        key: str,
    ) -> dict[str, Any]:
        stmt = select(Configuration.tenant_key, Configuration.value).where(
            Configuration.key == key,
            Configuration.tenant_key.isnot(None),
        )
        result = await session.execute(stmt)
        return dict(result.all())


    async def check_admin_user_exists(
        self,
        session: AsyncSession,
    ) -> bool:
        stmt = select(User).where(User.role == "admin").limit(1)
        with tenant_isolation_bypass(
            session,
            reason="setup guard checks for any admin user across tenants",
            models=(User,),
        ):
            result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None


    async def execute_health_check(
        self,
        session: AsyncSession,
    ) -> bool:
        try:
            await session.execute(text("SELECT 1"))
            return True
        except (RuntimeError, OSError):
            return False
