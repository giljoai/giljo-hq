# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.auth import User, UserFieldPriority


logger = logging.getLogger(__name__)


class UserRepository:

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")


    async def list_users(
        self,
        session: AsyncSession,
        tenant_key: str,
        include_all_tenants: bool = False,
    ) -> list[User]:
        if include_all_tenants:
            stmt = select(User).order_by(User.created_at)
        else:
            stmt = select(User).where(User.tenant_key == tenant_key).order_by(User.created_at)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_user_by_id(
        self,
        session: AsyncSession,
        user_id: str,
        tenant_key: str,
        include_all_tenants: bool = False,
    ) -> User | None:
        if include_all_tenants:
            stmt = select(User).where(User.id == user_id)
        else:
            stmt = select(User).where(and_(User.id == user_id, User.tenant_key == tenant_key))
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def check_username_exists(self, session: AsyncSession, username: str) -> bool:
        stmt = select(User).where(User.username == username)
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def check_email_exists(self, session: AsyncSession, email: str) -> bool:
        stmt = select(User).where(User.email == email)
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_first_active_admin(self, session: AsyncSession, tenant_key: str) -> User | None:
        result = await session.execute(
            select(User).where(User.tenant_key == tenant_key, User.role == "admin", User.is_active.is_(True)).limit(1)
        )
        return result.scalar_one_or_none()

    async def add_user(self, session: AsyncSession, user: User) -> User:
        session.add(user)
        await session.flush()
        await session.refresh(user)
        return user

    async def soft_delete_user(self, session: AsyncSession, user: User) -> None:
        user.is_active = False
        await session.flush()


    async def get_field_priorities(
        self,
        session: AsyncSession,
        user_id: str,
        tenant_key: str,
    ) -> list[UserFieldPriority]:
        stmt = select(UserFieldPriority).where(
            and_(
                UserFieldPriority.user_id == user_id,
                UserFieldPriority.tenant_key == tenant_key,
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def add_field_priority(self, session: AsyncSession, priority: UserFieldPriority) -> None:
        session.add(priority)

    async def delete_field_priority(self, session: AsyncSession, priority: UserFieldPriority) -> None:
        await session.delete(priority)

    async def count_admins_excluding(
        self,
        session: AsyncSession,
        tenant_key: str,
        exclude_user_id: str,
    ) -> int:
        from sqlalchemy import func

        stmt = select(func.count(User.id)).where(
            and_(User.tenant_key == tenant_key, User.role == "admin", User.is_active, User.id != exclude_user_id)
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def bulk_disable_field_priority(
        self,
        session: AsyncSession,
        tenant_key: str,
        category: str,
    ) -> int:
        stmt = (
            update(UserFieldPriority)
            .where(
                and_(
                    UserFieldPriority.tenant_key == tenant_key,
                    UserFieldPriority.category == category,
                    UserFieldPriority.enabled.is_(True),
                )
            )
            .values(enabled=False, updated_at=datetime.now(UTC))
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount
