# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.exceptions import (
    AuthorizationError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.auth import User




@pytest.mark.asyncio
async def test_list_users_returns_users_for_tenant(user_service, db_session, test_user, test_tenant_key):
    users = await user_service.list_users()

    assert isinstance(users, list)
    assert len(users) >= 1

    for u in users:
        assert isinstance(u, User)

    usernames = [u.username for u in users]
    assert test_user.username in usernames


@pytest.mark.asyncio
async def test_list_users_tenant_isolation(user_service, db_session, test_tenant_key):
    other_tenant = f"other_tenant_{uuid4().hex[:8]}"
    other_user = User(
        id=str(uuid4()),
        username=f"otheruser_{uuid4().hex[:6]}",
        email=f"other_{uuid4().hex[:6]}@example.com",
        password_hash=bcrypt.hashpw(b"OtherPassword123", bcrypt.gensalt()).decode("utf-8"),
        tenant_key=other_tenant,
        role="developer",
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.commit()

    users = await user_service.list_users()

    assert isinstance(users, list)
    for u in users:
        assert isinstance(u, User)
    usernames = [u.username for u in users]
    assert other_user.username not in usernames


@pytest.mark.asyncio
async def test_list_users_includes_inactive(user_service, db_session, test_tenant_key):
    inactive_user = User(
        id=str(uuid4()),
        username=f"inactive_{uuid4().hex[:6]}",
        email=f"inactive_{uuid4().hex[:6]}@example.com",
        password_hash=bcrypt.hashpw(b"Password123", bcrypt.gensalt()).decode("utf-8"),
        tenant_key=test_tenant_key,
        role="developer",
        is_active=False,
    )
    db_session.add(inactive_user)
    await db_session.commit()

    users = await user_service.list_users()

    assert isinstance(users, list)
    for u in users:
        assert isinstance(u, User)
    usernames = [u.username for u in users]
    assert inactive_user.username in usernames




@pytest.mark.asyncio
async def test_get_user_returns_user_by_id(user_service, test_user):
    user = await user_service.get_user(test_user.id)

    assert isinstance(user, User)
    assert user.id == test_user.id
    assert user.username == test_user.username
    assert user.email == test_user.email


@pytest.mark.asyncio
async def test_get_user_not_found(user_service):
    fake_id = str(uuid4())

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await user_service.get_user(fake_id)

    assert "not found" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_get_user_tenant_isolation(user_service, db_session):
    other_tenant = f"other_tenant_{uuid4().hex[:8]}"
    other_user = User(
        id=str(uuid4()),
        username=f"otheruser_{uuid4().hex[:6]}",
        email=f"other_{uuid4().hex[:6]}@example.com",
        password_hash=bcrypt.hashpw(b"Password123", bcrypt.gensalt()).decode("utf-8"),
        tenant_key=other_tenant,
        role="developer",
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.commit()

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await user_service.get_user(other_user.id)

    assert "not found" in str(exc_info.value).lower()




@pytest.mark.asyncio
async def test_create_user_success(user_service, test_tenant_key):
    username = f"newuser_{uuid4().hex[:6]}"
    email = f"new_{uuid4().hex[:6]}@example.com"

    user = await user_service.create_user(
        username=username,
        email=email,
        first_name="New",
        last_name="User",
        password="NewPassword123",
        role="developer",
    )

    assert isinstance(user, User)
    assert user.username == username
    assert user.email == email
    assert user.role == "developer"
    assert user.is_active is True
    assert user.tenant_key == test_tenant_key
    assert user.first_name == "New"
    assert user.last_name == "User"
    assert user.full_name == "New User"


@pytest.mark.asyncio
async def test_create_user_duplicate_username(user_service, test_user):
    with pytest.raises(ValidationError) as exc_info:
        await user_service.create_user(
            username=test_user.username,
            email="different@example.com",
            password="Password123",
            role="developer",
        )

    error_msg = str(exc_info.value).lower()
    assert "already exists" in error_msg
    assert "username" in error_msg


@pytest.mark.asyncio
async def test_create_user_duplicate_email(user_service, test_user):
    with pytest.raises(ValidationError) as exc_info:
        await user_service.create_user(
            username=f"newuser_{uuid4().hex[:6]}",
            email=test_user.email,
            password="Password123",
            role="developer",
        )

    error_msg = str(exc_info.value).lower()
    assert "already exists" in error_msg
    assert "email" in error_msg


@pytest.mark.asyncio
async def test_create_user_missing_password_raises(user_service):
    username = f"newuser_{uuid4().hex[:6]}"

    with pytest.raises(ValidationError) as exc_info:
        await user_service.create_user(
            username=username,
            email=f"new_{uuid4().hex[:6]}@example.com",
            role="developer",
        )

    assert "password" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_create_user_empty_password_raises(user_service):
    username = f"newuser_{uuid4().hex[:6]}"

    with pytest.raises(ValidationError):
        await user_service.create_user(
            username=username,
            email=f"new_{uuid4().hex[:6]}@example.com",
            password="",
            role="developer",
        )


@pytest.mark.asyncio
async def test_create_user_does_not_hash_giljomcp_default(user_service):
    username = f"newuser_{uuid4().hex[:6]}"
    real_password = "AdminChosenPwd_4710!"

    user = await user_service.create_user(
        username=username,
        email=f"new_{uuid4().hex[:6]}@example.com",
        password=real_password,
        role="developer",
    )

    assert isinstance(user, User)
    assert bcrypt.checkpw(real_password.encode("utf-8"), user.password_hash.encode("utf-8"))
    assert not bcrypt.checkpw(b"GiljoMCP", user.password_hash.encode("utf-8"))
    assert user.must_change_password is False




@pytest.mark.asyncio
async def test_update_user_success(user_service, test_user):
    new_email = f"updated_{uuid4().hex[:6]}@example.com"

    user = await user_service.update_user(user_id=test_user.id, email=new_email, first_name="Updated", last_name="Name")

    assert isinstance(user, User)
    assert user.email == new_email
    assert user.first_name == "Updated"
    assert user.last_name == "Name"
    assert user.full_name == "Updated Name"


@pytest.mark.asyncio
async def test_update_user_not_found(user_service):
    fake_id = str(uuid4())

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await user_service.update_user(user_id=fake_id, email="new@example.com")

    assert "not found" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_update_user_duplicate_email(user_service, test_user, admin_user):
    with pytest.raises(ValidationError) as exc_info:
        await user_service.update_user(
            user_id=test_user.id,
            email=admin_user.email,
        )

    assert "already exists" in str(exc_info.value).lower()




@pytest.mark.asyncio
async def test_update_user_email_change_publishes_event(user_service, test_user, monkeypatch):
    from unittest.mock import AsyncMock

    from api import app_state

    old_email = test_user.email
    new_email = f"changed_{uuid4().hex[:6]}@example.com"

    fake_bus = AsyncMock()
    monkeypatch.setattr(app_state.state, "event_bus", fake_bus, raising=False)

    await user_service.update_user(user_id=test_user.id, email=new_email)

    fake_bus.publish.assert_awaited_once()
    event_type, payload = fake_bus.publish.await_args.args
    assert event_type == "user:email:changed"
    assert payload["old_email"] == old_email
    assert payload["new_email"] == new_email
    assert payload["user_id"] == test_user.id
    assert payload["tenant_key"] == user_service.tenant_key


@pytest.mark.asyncio
async def test_update_user_no_email_change_does_not_publish(user_service, test_user, monkeypatch):
    from unittest.mock import AsyncMock

    from api import app_state

    fake_bus = AsyncMock()
    monkeypatch.setattr(app_state.state, "event_bus", fake_bus, raising=False)

    await user_service.update_user(user_id=test_user.id, first_name="NoEmail", last_name="Change")

    fake_bus.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_user_same_email_does_not_publish(user_service, test_user, monkeypatch):
    from unittest.mock import AsyncMock

    from api import app_state

    fake_bus = AsyncMock()
    monkeypatch.setattr(app_state.state, "event_bus", fake_bus, raising=False)

    await user_service.update_user(user_id=test_user.id, email=test_user.email)

    fake_bus.publish.assert_not_awaited()




@pytest.mark.asyncio
async def test_set_recovery_pin_writes_hash_through_service(user_service, test_user, db_session):
    assert test_user.recovery_pin_hash is None

    await user_service.set_recovery_pin(test_user.id, "1234")

    await db_session.refresh(test_user)
    assert test_user.recovery_pin_hash is not None
    assert bcrypt.checkpw(b"1234", test_user.recovery_pin_hash.encode("utf-8"))


@pytest.mark.asyncio
async def test_set_recovery_pin_tenant_isolation(user_service, db_session):
    other_tenant = f"other_tenant_{uuid4().hex[:8]}"
    other_user = User(
        id=str(uuid4()),
        username=f"otheruser_{uuid4().hex[:6]}",
        email=f"other_{uuid4().hex[:6]}@example.com",
        password_hash=bcrypt.hashpw(b"OtherPassword123", bcrypt.gensalt()).decode("utf-8"),
        tenant_key=other_tenant,
        role="developer",
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.commit()

    with pytest.raises(ResourceNotFoundError):
        await user_service.set_recovery_pin(other_user.id, "1234")

    await db_session.refresh(other_user)
    assert other_user.recovery_pin_hash is None


@pytest.mark.asyncio
async def test_set_recovery_pin_rejects_non_4_digit(user_service, test_user):
    for bad in ("123", "12345", "abcd", ""):
        with pytest.raises(ValidationError):
            await user_service.set_recovery_pin(test_user.id, bad)




@pytest.mark.asyncio
async def test_delete_user_soft_delete(user_service, test_user, db_session):
    result = await user_service.delete_user(test_user.id)

    assert result is None

    await db_session.refresh(test_user)
    assert test_user.is_active is False


@pytest.mark.asyncio
async def test_delete_user_not_found(user_service):
    fake_id = str(uuid4())

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await user_service.delete_user(fake_id)

    assert "not found" in str(exc_info.value).lower()




@pytest.mark.asyncio
async def test_change_role_success(user_service, test_user, db_session):
    user = await user_service.auth.change_role(user_id=test_user.id, new_role="viewer")

    assert isinstance(user, User)
    assert user.role == "viewer"

    await db_session.refresh(test_user)
    assert test_user.role == "viewer"


@pytest.mark.asyncio
async def test_change_role_invalid_role(user_service, test_user):
    with pytest.raises(ValidationError) as exc_info:
        await user_service.auth.change_role(
            user_id=test_user.id,
            new_role="superuser",
        )

    assert "invalid" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_change_role_admin_restriction(user_service, admin_user):
    with pytest.raises(AuthorizationError) as exc_info:
        await user_service.auth.change_role(user_id=admin_user.id, new_role="developer")

    assert "admin" in str(exc_info.value).lower()
