# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import User




class TestCreateUserSplitName:

    @pytest.mark.asyncio
    async def test_create_with_first_and_last_stores_both_columns(self, user_service, db_session: AsyncSession):
        user = await user_service.create_user(
            username="split_fl_user",
            email="split_fl@example.com",
            first_name="Sam",
            last_name="Rivera",
            password="Password123!",
            role="developer",
        )

        assert isinstance(user, User)
        assert user.first_name == "Sam"
        assert user.last_name == "Rivera"

        with tenant_session_context(db_session, user.tenant_key):
            result = await db_session.execute(
                select(User).where(User.id == user.id, User.tenant_key == user.tenant_key)
            )
        db_user = result.scalar_one()
        assert db_user.first_name == "Sam"
        assert db_user.last_name == "Rivera"

    @pytest.mark.asyncio
    async def test_create_dual_writes_full_name_from_parts(self, user_service):
        user = await user_service.create_user(
            username="split_dual_user",
            email="split_dual@example.com",
            first_name="Jean",
            last_name="Claude",
            password="Password123!",
            role="developer",
        )

        assert user.full_name == "Jean Claude"

    @pytest.mark.asyncio
    async def test_create_with_first_name_only_no_last(self, user_service):
        user = await user_service.create_user(
            username="split_first_only",
            email="split_firstonly@example.com",
            first_name="Cher",
            password="Password123!",
            role="developer",
        )

        assert user.first_name == "Cher"
        assert user.last_name is None
        assert user.full_name == "Cher"

    @pytest.mark.asyncio
    async def test_create_with_neither_name_still_succeeds(self, user_service):
        user = await user_service.create_user(
            username="split_noname",
            email="split_noname@example.com",
            password="Password123!",
            role="developer",
        )

        assert user.first_name is None
        assert user.last_name is None




class TestUpdateUserSplitName:

    @pytest.mark.asyncio
    async def test_update_first_and_last_stores_to_columns(
        self, user_service, test_user: User, db_session: AsyncSession
    ):
        updated = await user_service.update_user(
            user_id=test_user.id,
            first_name="Updated",
            last_name="Name",
        )

        assert updated.first_name == "Updated"
        assert updated.last_name == "Name"

        user_id = test_user.id
        db_session.expire(test_user)
        result = await db_session.execute(select(User).where(User.id == user_id))
        db_user = result.scalar_one()
        assert db_user.first_name == "Updated"
        assert db_user.last_name == "Name"

    @pytest.mark.asyncio
    async def test_update_dual_writes_full_name(self, user_service, test_user: User):
        updated = await user_service.update_user(
            user_id=test_user.id,
            first_name="Jean",
            last_name="Dupont",
        )

        assert updated.full_name == "Jean Dupont"

    @pytest.mark.asyncio
    async def test_update_first_name_only_clears_last(self, user_service, test_user: User, db_session: AsyncSession):
        updated = await user_service.update_user(
            user_id=test_user.id,
            first_name="Solo",
            last_name=None,
        )

        assert updated.first_name == "Solo"
        assert updated.last_name is None
        assert updated.full_name == "Solo"

    @pytest.mark.asyncio
    async def test_update_tenant_isolation_other_tenant_not_affected(
        self, user_service, test_user: User, db_session: AsyncSession, other_tenant_user: User
    ):
        other_user_id = other_tenant_user.id
        original_first_name = other_tenant_user.first_name

        await user_service.update_user(
            user_id=test_user.id,
            first_name="TenantAFirst",
            last_name="TenantALast",
        )

        await db_session.commit()
        result = await db_session.execute(select(User).where(User.id == other_user_id))
        other = result.scalar_one()
        assert other.first_name == original_first_name, (
            "Tenant B user's first_name was mutated by a Tenant A update_user call"
        )




class TestUserDisplayNameProperty:

    def _make_user(
        self,
        username: str = "testuser",
        first_name: str | None = None,
        last_name: str | None = None,
        full_name: str | None = None,
    ) -> object:
        import types

        u = types.SimpleNamespace(
            username=username,
            first_name=first_name,
            last_name=last_name,
            full_name=full_name,
        )
        u.display_name = User.display_name.fget(u)  # type: ignore[attr-defined]
        return u

    def test_display_name_uses_first_and_last_when_both_set(self):
        u = self._make_user(first_name="Sam", last_name="Rivera")
        assert u.display_name == "Sam Rivera"

    def test_display_name_uses_first_only_when_no_last(self):
        u = self._make_user(first_name="Cher")
        assert u.display_name == "Cher"

    def test_display_name_falls_back_to_full_name_when_first_last_empty(self):
        u = self._make_user(full_name="Legacy Full Name")
        assert u.display_name == "Legacy Full Name"

    def test_display_name_falls_back_to_username_when_all_name_cols_null(self):
        u = self._make_user(username="jdoe")
        assert u.display_name == "jdoe"

    def test_display_name_empty_strings_treated_as_missing(self):
        u = self._make_user(first_name="", last_name="", full_name="Fallback")
        assert u.display_name == "Fallback"

    def test_display_name_prefers_split_cols_over_full_name_when_both_set(self):
        u = self._make_user(first_name="New", last_name="Name", full_name="Old Full Name")
        assert u.display_name == "New Name"
