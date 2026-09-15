# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import bcrypt
import pytest
from sqlalchemy import select

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.auth import User
from giljo_mcp.schemas.service_responses import UserInfo




class TestRegisterUser:

    @pytest.mark.asyncio
    async def test_register_user_success(self, auth_service, auth_user_with_password, db_session):
        admin_user, _ = auth_user_with_password

        result = await auth_service.register_user(
            username="newuser",
            email="new@example.com",
            password="NewPassword123!",
            role="developer",
            requesting_admin_id=admin_user.id,
        )

        assert isinstance(result, UserInfo)
        assert result.username == "newuser"
        assert result.email == "new@example.com"
        assert result.role == "developer"
        assert result.tenant_key is not None

        stmt = select(User).where(User.username == "newuser")
        result_db = await db_session.execute(stmt)
        new_user = result_db.scalar_one()
        assert new_user.password_hash != "NewPassword123!"
        assert bcrypt.checkpw(b"NewPassword123!", new_user.password_hash.encode("utf-8"))

    @pytest.mark.asyncio
    async def test_register_user_persists_registration_ip(self, auth_service, auth_user_with_password, db_session):
        admin_user, _ = auth_user_with_password

        await auth_service.register_user(
            username="ipuser",
            email="ipuser@example.com",
            password="NewPassword123!",
            role="developer",
            requesting_admin_id=admin_user.id,
            registration_ip="203.0.113.7",
        )

        stmt = select(User).where(User.username == "ipuser")
        new_user = (await db_session.execute(stmt)).scalar_one()
        assert new_user.registration_ip == "203.0.113.7"

    @pytest.mark.asyncio
    async def test_register_user_registration_ip_nullable(self, auth_service, auth_user_with_password, db_session):
        admin_user, _ = auth_user_with_password

        await auth_service.register_user(
            username="noipuser",
            email="noipuser@example.com",
            password="NewPassword123!",
            role="developer",
            requesting_admin_id=admin_user.id,
        )

        stmt = select(User).where(User.username == "noipuser")
        new_user = (await db_session.execute(stmt)).scalar_one()
        assert new_user.registration_ip is None

    @pytest.mark.asyncio
    async def test_register_user_duplicate_username(self, auth_service, auth_user_with_password):
        admin_user, _ = auth_user_with_password

        with pytest.raises(ValidationError) as exc_info:
            await auth_service.register_user(
                username=admin_user.username,
                email="different@example.com",
                password="Password123!",
                role="developer",
                requesting_admin_id=admin_user.id,
            )

        assert "already exists" in str(exc_info.value).lower()


class TestCreateFirstAdmin:

    @pytest.mark.asyncio
    async def test_create_first_admin_fails_when_users_exist(self, auth_service, auth_user_with_password):

        with pytest.raises(ValidationError) as exc_info:
            await auth_service.create_first_admin(
                username="secondadmin",
                email="second@example.com",
                password="SecureAdmin123!@#",
                full_name=None,
                first_name="Second",
                last_name="Admin",
            )

        assert "already exists" in str(exc_info.value).lower() or "Administrator account already exists" in str(
            exc_info.value
        )
