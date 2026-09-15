# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, MagicMock, Mock

import bcrypt
import pytest

from giljo_mcp.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.services.user_auth_service import UserAuthService



TENANT_KEY = "test-tenant"


def _make_user(
    user_id="user-1",
    username="testuser",
    email="test@example.com",
    role="developer",
    is_active=True,
    password="secret123",
    tenant_key=TENANT_KEY,
):
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user = MagicMock()
    user.id = user_id
    user.username = username
    user.email = email
    user.role = role
    user.is_active = is_active
    user.password_hash = pw_hash
    user.must_change_password = True
    user.tenant_key = tenant_key
    return user


def _make_session():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = Mock()
    session.delete = Mock()
    session.info = {}
    return session


def _make_service(session, tenant_key=TENANT_KEY):
    db_manager = Mock()
    db_manager.get_session_async = Mock(return_value=session)
    return UserAuthService(db_manager=db_manager, tenant_key=tenant_key, session=session)




class TestChangePassword:

    @pytest.mark.asyncio
    async def test_change_password_user_not_found_raises(self):
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError):
            await service.change_password("nonexistent", "old", "new")

    @pytest.mark.asyncio
    async def test_change_password_non_admin_requires_old_password(self):
        user = _make_user()
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ValidationError, match="Current password is required"):
            await service.change_password("user-1", None, "newpass")

    @pytest.mark.asyncio
    async def test_change_password_wrong_old_password_raises(self):
        user = _make_user(password="correct-password")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(AuthenticationError, match="Current password is incorrect"):
            await service.change_password("user-1", "wrong-password", "newpass")

    @pytest.mark.asyncio
    async def test_change_password_success_non_admin(self):
        user = _make_user(password="correct-password")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        await service.change_password("user-1", "correct-password", "new-password")

        assert user.password_hash != ""
        assert user.must_change_password is False
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_change_password_admin_bypasses_old_password(self):
        user = _make_user(password="original")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        await service.change_password("user-1", None, "new-password", is_admin=True)

        assert user.must_change_password is False
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_change_password_query_filters_by_tenant_key(self):
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session, tenant_key="my-tenant")

        with pytest.raises(ResourceNotFoundError):
            await service.change_password("user-1", "old", "new")

        session.execute.assert_called_once()
        call_args = session.execute.call_args[0][0]
        compiled = str(call_args.compile(compile_kwargs={"literal_binds": True}))
        assert "tenant_key" in compiled




class TestVerifyPassword:

    @pytest.mark.asyncio
    async def test_verify_password_correct(self):
        user = _make_user(password="correct")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service.verify_password("user-1", "correct")
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_password_incorrect(self):
        user = _make_user(password="correct")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service.verify_password("user-1", "wrong")
        assert result is False

    @pytest.mark.asyncio
    async def test_verify_password_user_not_found(self):
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError):
            await service.verify_password("nonexistent", "password")




class TestUsernameEmailChecks:

    @pytest.mark.asyncio
    async def test_username_exists_returns_true(self):
        user = _make_user(username="existing")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service.check_username_exists("existing")
        assert result is True

    @pytest.mark.asyncio
    async def test_username_not_exists_returns_false(self):
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service.check_username_exists("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_email_exists_returns_true(self):
        user = _make_user(email="taken@example.com")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service.check_email_exists("taken@example.com")
        assert result is True

    @pytest.mark.asyncio
    async def test_email_not_exists_returns_false(self):
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service.check_email_exists("new@example.com")
        assert result is False




class TestChangeRole:

    @pytest.mark.asyncio
    async def test_change_role_invalid_role_raises(self):
        session = _make_session()
        service = _make_service(session)
        with pytest.raises(ValidationError, match="Invalid role"):
            await service.change_role("user-1", "superuser")

    @pytest.mark.asyncio
    async def test_change_role_user_not_found_raises(self):
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError):
            await service.change_role("nonexistent", "developer")

    @pytest.mark.asyncio
    async def test_change_role_demote_last_admin_raises(self):
        user = _make_user(role="admin")
        session = _make_session()

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        call_count = 0

        async def side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_user_result
            return mock_count_result

        session.execute = AsyncMock(side_effect=side_effect)

        service = _make_service(session)
        with pytest.raises(AuthorizationError, match="last admin"):
            await service.change_role("user-1", "developer")

    @pytest.mark.asyncio
    async def test_change_role_success(self):
        user = _make_user(role="developer")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        await service.change_role("user-1", "viewer")

        assert user.role == "viewer"
        session.commit.assert_called_once()
        session.refresh.assert_called_once_with(user)

    @pytest.mark.asyncio
    async def test_change_role_admin_to_admin_no_guard(self):
        user = _make_user(role="admin")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        await service.change_role("user-1", "admin")

        assert user.role == "admin"
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_change_role_query_filters_by_tenant_key(self):
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session, tenant_key="isolated-tenant")

        with pytest.raises(ResourceNotFoundError):
            await service.change_role("user-1", "developer")

        call_args = session.execute.call_args[0][0]
        compiled = str(call_args.compile(compile_kwargs={"literal_binds": True}))
        assert "tenant_key" in compiled




class TestForceLogout:

    @pytest.mark.asyncio
    async def test_force_logout_increments_epoch(self):
        user = _make_user()
        user.token_revocation_epoch = 2
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service.force_logout("user-1")

        assert result.token_revocation_epoch == 3
        session.commit.assert_called_once()
        session.refresh.assert_called_once_with(user)

    @pytest.mark.asyncio
    async def test_force_logout_from_none_epoch_starts_at_one(self):
        user = _make_user()
        user.token_revocation_epoch = None
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service.force_logout("user-1")

        assert result.token_revocation_epoch == 1

    @pytest.mark.asyncio
    async def test_force_logout_user_not_found_raises(self):
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError):
            await service.force_logout("nonexistent")
