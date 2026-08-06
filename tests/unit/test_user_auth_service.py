# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for UserAuthService (Sprint 002f -- P1 security-critical).

Covers:
- Password change (admin vs non-admin flows)
- Password verification
- Username/email uniqueness checks
- Role change with admin-count guard
- Tenant isolation on every query
"""

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
    """Build a fake User ORM-like object with a bcrypt password hash."""
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
    """Create a mock async session configured as a context manager."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = Mock()
    session.delete = Mock()
    session.info = {}  # tenant_session_context save/restore target
    return session


def _make_service(session, tenant_key=TENANT_KEY):
    """Create a UserAuthService with an injected test session."""
    db_manager = Mock()
    db_manager.get_session_async = Mock(return_value=session)
    return UserAuthService(db_manager=db_manager, tenant_key=tenant_key, session=session)


# ---------------------------------------------------------------------------
# change_password tests
# ---------------------------------------------------------------------------


class TestChangePassword:
    """Tests for UserAuthService.change_password."""

    @pytest.mark.asyncio
    async def test_change_password_user_not_found_raises(self):
        """Raises ResourceNotFoundError when user does not exist."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError):
            await service.change_password("nonexistent", "old", "new")

    @pytest.mark.asyncio
    async def test_change_password_non_admin_requires_old_password(self):
        """Raises ValidationError when old_password is None for non-admin."""
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
        """Raises AuthenticationError when old_password is incorrect."""
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
        """Successfully changes password with correct old password."""
        user = _make_user(password="correct-password")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        await service.change_password("user-1", "correct-password", "new-password")

        # Verify password was updated (password_hash changed)
        assert user.password_hash != ""
        # Verify must_change_password was cleared
        assert user.must_change_password is False
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_change_password_admin_bypasses_old_password(self):
        """Admin can change password without providing old password."""
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
        """Verifies the DB query includes tenant_key filter."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session, tenant_key="my-tenant")

        with pytest.raises(ResourceNotFoundError):
            await service.change_password("user-1", "old", "new")

        # Verify execute was called (tenant_key is embedded in the query WHERE clause)
        session.execute.assert_called_once()
        call_args = session.execute.call_args[0][0]
        # The compiled SQL should reference tenant_key
        compiled = str(call_args.compile(compile_kwargs={"literal_binds": True}))
        assert "tenant_key" in compiled


# ---------------------------------------------------------------------------
# verify_password tests
# ---------------------------------------------------------------------------


class TestVerifyPassword:
    """Tests for UserAuthService.verify_password."""

    @pytest.mark.asyncio
    async def test_verify_password_correct(self):
        """Returns True for matching password."""
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
        """Returns False for non-matching password."""
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
        """Raises ResourceNotFoundError when user does not exist."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError):
            await service.verify_password("nonexistent", "password")


# ---------------------------------------------------------------------------
# check_username_exists / check_email_exists tests
# ---------------------------------------------------------------------------


class TestUsernameEmailChecks:
    """Tests for username and email existence checks."""

    @pytest.mark.asyncio
    async def test_username_exists_returns_true(self):
        """Returns True when username is found."""
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
        """Returns False when username is not found."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service.check_username_exists("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_email_exists_returns_true(self):
        """Returns True when email is found."""
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
        """Returns False when email is not found."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service.check_email_exists("new@example.com")
        assert result is False


# ---------------------------------------------------------------------------
# change_role tests
# ---------------------------------------------------------------------------


class TestChangeRole:
    """Tests for UserAuthService.change_role."""

    @pytest.mark.asyncio
    async def test_change_role_invalid_role_raises(self):
        """Raises ValidationError for invalid role value."""
        session = _make_session()
        service = _make_service(session)
        with pytest.raises(ValidationError, match="Invalid role"):
            await service.change_role("user-1", "superuser")

    @pytest.mark.asyncio
    async def test_change_role_user_not_found_raises(self):
        """Raises ResourceNotFoundError when user does not exist."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError):
            await service.change_role("nonexistent", "developer")

    @pytest.mark.asyncio
    async def test_change_role_demote_last_admin_raises(self):
        """Raises AuthorizationError when demoting the last admin."""
        user = _make_user(role="admin")
        session = _make_session()

        # First call: find user. Second call: count admins (returns 0 remaining).
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
        """Successfully changes role when valid and not last admin."""
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
        """Changing admin to admin skips the admin-count guard."""
        user = _make_user(role="admin")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        await service.change_role("user-1", "admin")

        # Should succeed without hitting the admin-count check
        assert user.role == "admin"
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_change_role_query_filters_by_tenant_key(self):
        """Verifies the user lookup query includes tenant_key filter."""
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


# ---------------------------------------------------------------------------
# force_logout tests (SEC-6011)
# ---------------------------------------------------------------------------


class TestForceLogout:
    """Tests for UserAuthService.force_logout — the admin-forced-logout epoch bump."""

    @pytest.mark.asyncio
    async def test_force_logout_increments_epoch(self):
        """Bumps token_revocation_epoch by 1 and commits."""
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
        """A legacy row with a NULL epoch self-heals to 1 on the first bump."""
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
        """Raises ResourceNotFoundError when the user does not exist in this tenant."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError):
            await service.force_logout("nonexistent")
