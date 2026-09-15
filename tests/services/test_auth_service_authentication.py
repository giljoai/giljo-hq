# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from uuid import uuid4

import bcrypt
import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ResourceNotFoundError,
)
from giljo_mcp.models.auth import User
from giljo_mcp.models.config import SetupState
from giljo_mcp.models.organizations import Organization
from giljo_mcp.schemas.service_responses import (
    AuthResult,
    SetupStateInfo,
)




@pytest_asyncio.fixture
async def auth_inactive_org(db_session):
    unique_id = str(uuid4())[:8]
    org = Organization(
        id=str(uuid4()),
        tenant_key=f"test_tenant_inactive_{unique_id}",
        name=f"Test Organization Inactive {unique_id}",
        slug=f"test-org-inactive-{unique_id}",
        is_active=True,
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest_asyncio.fixture
async def auth_inactive_user(db_session, auth_inactive_org):
    unique_id = str(uuid4())[:8]
    password = "Inactive1234!"
    user = User(
        id=str(uuid4()),
        username=f"inactiveuser_{unique_id}",
        email=f"inactive_{unique_id}@example.com",
        password_hash=bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
        role="developer",
        tenant_key=auth_inactive_org.tenant_key,
        org_id=auth_inactive_org.id,
        is_active=False,
        created_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user, password


@pytest_asyncio.fixture
async def auth_setup_state(db_session, auth_test_org):
    state = SetupState(
        id=str(uuid4()),
        tenant_key=auth_test_org.tenant_key,
        database_initialized=True,
        database_initialized_at=datetime.now(UTC),
        first_admin_created=False,
    )
    db_session.add(state)
    await db_session.commit()
    await db_session.refresh(state)
    return state




class TestAuthenticateUser:

    @pytest.mark.asyncio
    async def test_authenticate_user_success(self, auth_service, auth_user_with_password):
        user, password = auth_user_with_password

        result = await auth_service.authenticate_user(user.username, password)

        assert isinstance(result, AuthResult)
        assert result.user_id == user.id
        assert result.username == user.username
        assert result.tenant_key == user.tenant_key
        assert result.role == user.role
        assert result.email == user.email
        assert result.is_active is True
        assert result.token.startswith("eyJ")

    @pytest.mark.asyncio
    async def test_authenticate_user_invalid_password(self, auth_service, auth_user_with_password):
        user, _ = auth_user_with_password

        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.authenticate_user(user.username, "WrongPassword123!")

        assert "Invalid credentials" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_authenticate_user_nonexistent_username(self, auth_service):

        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.authenticate_user("nonexistent", "Password123!")

        assert "Invalid credentials" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_authenticate_user_inactive_account(self, auth_service, auth_inactive_user):
        user, password = auth_inactive_user

        with pytest.raises(AuthorizationError) as exc_info:
            await auth_service.authenticate_user(user.username, password)

        assert "inactive" in str(exc_info.value).lower()


    @pytest.mark.asyncio
    async def test_authenticate_user_by_username_succeeds(self, auth_service, auth_user_with_password):
        user, password = auth_user_with_password

        result = await auth_service.authenticate_user(user.username, password)

        assert isinstance(result, AuthResult)
        assert result.user_id == user.id
        assert result.username == user.username

    @pytest.mark.asyncio
    async def test_authenticate_user_by_email_succeeds(self, auth_service, auth_user_with_password):
        user, password = auth_user_with_password

        result = await auth_service.authenticate_user(user.email, password)

        assert isinstance(result, AuthResult)
        assert result.user_id == user.id
        assert result.email == user.email

    @pytest.mark.asyncio
    async def test_authenticate_user_by_email_is_case_insensitive(self, auth_service, auth_user_with_password):
        user, password = auth_user_with_password

        result = await auth_service.authenticate_user(user.email.upper(), password)

        assert isinstance(result, AuthResult)
        assert result.user_id == user.id

    @pytest.mark.asyncio
    async def test_authenticate_user_unknown_identifier_raises_invalid_credentials(self, auth_service):
        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.authenticate_user("nobody@nowhere.example", "Password123!")

        assert "Invalid credentials" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_authenticate_user_null_password_hash_fails_generically(
        self, auth_service, db_session, auth_test_org
    ):
        unique_id = str(uuid4())[:8]
        user = User(
            id=str(uuid4()),
            username=f"socialonly_{unique_id}",
            email=f"socialonly_{unique_id}@example.com",
            password_hash=None,
            role="admin",
            tenant_key=auth_test_org.tenant_key,
            org_id=auth_test_org.id,
            is_active=True,
            created_at=datetime.now(UTC),
        )
        db_session.add(user)
        await db_session.commit()

        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.authenticate_user(user.username, "SomeGuess123!")

        assert "Invalid credentials" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_authenticate_user_username_match_wins_over_email_match(
        self, auth_service, db_session, auth_test_org
    ):
        from datetime import datetime
        from uuid import uuid4

        import bcrypt

        from giljo_mcp.models.auth import User

        shared = f"collide_{uuid4().hex[:8]}"
        pw_username_owner = "UserWins1!"
        pw_email_owner = "EmailOwner1!"

        user_username_owner = User(
            id=str(uuid4()),
            username=shared,
            email=f"{shared}_unrelated@example.com",
            password_hash=bcrypt.hashpw(pw_username_owner.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
            role="developer",
            tenant_key=auth_test_org.tenant_key,
            org_id=auth_test_org.id,
            is_active=True,
            created_at=datetime.now(UTC),
        )
        user_email_owner = User(
            id=str(uuid4()),
            username=f"other_{uuid4().hex[:8]}",
            email=shared,
            password_hash=bcrypt.hashpw(pw_email_owner.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
            role="developer",
            tenant_key=auth_test_org.tenant_key,
            org_id=auth_test_org.id,
            is_active=True,
            created_at=datetime.now(UTC),
        )
        db_session.add_all([user_username_owner, user_email_owner])
        await db_session.commit()

        result = await auth_service.authenticate_user(shared, pw_username_owner)
        assert result.user_id == user_username_owner.id

        with pytest.raises(AuthenticationError):
            await auth_service.authenticate_user(shared, pw_email_owner)


    @pytest.mark.asyncio
    async def test_authenticate_user_overlong_password_known_account_fails_closed(
        self, auth_service, auth_user_with_password
    ):
        user, _ = auth_user_with_password

        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.authenticate_user(user.username, "A" * 100)

        assert "Invalid credentials" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_authenticate_user_overlong_password_unknown_account_identical_response(self, auth_service):
        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.authenticate_user(f"ghost_{uuid4().hex[:8]}", "A" * 100)

        assert "Invalid credentials" in str(exc_info.value)


class TestLoginTimingOracleEqualized:

    @staticmethod
    def _spy_on_verify(monkeypatch):
        import giljo_mcp.services.auth_service as svc

        real = svc.async_verify_password
        hashes_seen: list[str] = []

        async def spy(plaintext, password_hash):
            hashes_seen.append(password_hash)
            return await real(plaintext, password_hash)

        monkeypatch.setattr(svc, "async_verify_password", spy)
        return hashes_seen

    @pytest.mark.asyncio
    async def test_real_user_wrong_password_verifies_exactly_once(
        self, auth_service, auth_user_with_password, monkeypatch
    ):
        hashes_seen = self._spy_on_verify(monkeypatch)
        user, _ = auth_user_with_password

        with pytest.raises(AuthenticationError):
            await auth_service.authenticate_user(user.username, "WrongPassword123!")

        assert len(hashes_seen) == 1
        assert hashes_seen[0] == user.password_hash

    @pytest.mark.asyncio
    async def test_missing_user_verifies_exactly_once_against_dummy(self, auth_service, monkeypatch):
        from giljo_mcp.utils.password_helper import DUMMY_BCRYPT_HASH

        hashes_seen = self._spy_on_verify(monkeypatch)

        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.authenticate_user(f"ghost_{uuid4().hex[:8]}", "Password123!")

        assert "Invalid credentials" in str(exc_info.value)
        assert len(hashes_seen) == 1
        assert hashes_seen[0] == DUMMY_BCRYPT_HASH

    @pytest.mark.asyncio
    async def test_null_hash_user_verifies_exactly_once_against_dummy(
        self, auth_service, db_session, auth_test_org, monkeypatch
    ):
        from giljo_mcp.utils.password_helper import DUMMY_BCRYPT_HASH

        unique_id = str(uuid4())[:8]
        user = User(
            id=str(uuid4()),
            username=f"socialonly_{unique_id}",
            email=f"socialonly_{unique_id}@example.com",
            password_hash=None,
            role="admin",
            tenant_key=auth_test_org.tenant_key,
            org_id=auth_test_org.id,
            is_active=True,
            created_at=datetime.now(UTC),
        )
        db_session.add(user)
        await db_session.commit()

        hashes_seen = self._spy_on_verify(monkeypatch)

        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.authenticate_user(user.username, "SomeGuess123!")

        assert "Invalid credentials" in str(exc_info.value)
        assert len(hashes_seen) == 1
        assert hashes_seen[0] == DUMMY_BCRYPT_HASH

    @pytest.mark.asyncio
    async def test_successful_login_still_one_verify(self, auth_service, auth_user_with_password, monkeypatch):
        hashes_seen = self._spy_on_verify(monkeypatch)
        user, password = auth_user_with_password

        result = await auth_service.authenticate_user(user.username, password)

        assert isinstance(result, AuthResult)
        assert len(hashes_seen) == 1
        assert hashes_seen[0] == user.password_hash


class TestUpdateLastLogin:

    @pytest.mark.asyncio
    async def test_update_last_login_success(self, auth_service, auth_user_with_password, db_session):
        user, _ = auth_user_with_password
        original_last_login = user.last_login
        new_timestamp = datetime.now(UTC)

        result = await auth_service.update_last_login(user.id, new_timestamp)
        assert result is None

        stmt = select(User).where(User.id == user.id)
        result_db = await db_session.execute(stmt)
        updated_user = result_db.scalar_one()
        assert updated_user.last_login is not None
        assert updated_user.last_login != original_last_login

    @pytest.mark.asyncio
    async def test_update_last_login_nonexistent_user(self, auth_service):

        with pytest.raises(ResourceNotFoundError):
            await auth_service.update_last_login("nonexistent-user-id", datetime.now(UTC))


class TestCheckSetupState:

    @pytest.mark.asyncio
    async def test_check_setup_state_exists(self, auth_service, auth_setup_state):
        result = await auth_service.check_setup_state(auth_setup_state.tenant_key)

        assert result is not None
        assert isinstance(result, SetupStateInfo)
        assert result.first_admin_created is False
        assert result.database_initialized is True
        assert result.tenant_key == auth_setup_state.tenant_key

    @pytest.mark.asyncio
    async def test_check_setup_state_not_found(self, auth_service):
        result = await auth_service.check_setup_state("nonexistent_tenant")

        assert result is None
