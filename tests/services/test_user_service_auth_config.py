# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import bcrypt
import pytest

from giljo_mcp.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.auth import User




@pytest.mark.asyncio
async def test_change_password_success(user_service, test_user, db_session):
    new_password = "NewPassword456"

    result = await user_service.auth.change_password(
        user_id=test_user.id, old_password="TestPassword123", new_password=new_password
    )

    assert result is None

    await db_session.refresh(test_user)
    assert bcrypt.checkpw(new_password.encode("utf-8"), test_user.password_hash.encode("utf-8"))


@pytest.mark.asyncio
async def test_change_password_incorrect_old_password(user_service, test_user):
    with pytest.raises(AuthenticationError) as exc_info:
        await user_service.auth.change_password(
            user_id=test_user.id, old_password="WrongPassword", new_password="NewPassword456"
        )

    assert "incorrect" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_change_password_admin_bypass(user_service, test_user, db_session):
    new_password = "AdminSetPassword789"

    result = await user_service.auth.change_password(
        user_id=test_user.id,
        old_password=None,
        new_password=new_password,
        is_admin=True,
    )

    assert result is None

    await db_session.refresh(test_user)
    assert bcrypt.checkpw(new_password.encode("utf-8"), test_user.password_hash.encode("utf-8"))




@pytest.mark.asyncio
async def test_set_initial_password_success_for_passwordless_user(user_service, db_session, test_tenant_key):
    user = User(
        id=str(uuid4()),
        username=f"social_{uuid4().hex[:8]}",
        email=f"social_{uuid4().hex[:8]}@example.com",
        password_hash=None,
        role="developer",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    new_password = "InitialPass123!"
    result = await user_service.auth.set_initial_password(user_id=user.id, new_password=new_password)

    assert result is None
    await db_session.refresh(user)
    assert user.password_hash is not None
    assert bcrypt.checkpw(new_password.encode("utf-8"), user.password_hash.encode("utf-8"))
    assert user.password_nudge_dismissed_at is not None


@pytest.mark.asyncio
async def test_set_initial_password_rejects_user_with_existing_password(user_service, test_user):
    original_hash = test_user.password_hash
    assert original_hash is not None

    with pytest.raises(AuthorizationError) as exc_info:
        await user_service.auth.set_initial_password(user_id=test_user.id, new_password="SomeNewPass123!")

    assert "already" in str(exc_info.value).lower()
    assert test_user.password_hash == original_hash


@pytest.mark.asyncio
async def test_set_initial_password_user_not_found(user_service):
    with pytest.raises(ResourceNotFoundError):
        await user_service.auth.set_initial_password(user_id=str(uuid4()), new_password="SomeNewPass123!")




@pytest.mark.asyncio
async def test_check_username_exists_true(user_service, test_user):
    exists = await user_service.auth.check_username_exists(test_user.username)

    assert exists is True


@pytest.mark.asyncio
async def test_check_username_exists_false(user_service):
    exists = await user_service.auth.check_username_exists(f"nonexistent_{uuid4().hex}")

    assert exists is False




@pytest.mark.asyncio
async def test_check_email_exists_true(user_service, test_user):
    exists = await user_service.auth.check_email_exists(test_user.email)

    assert exists is True


@pytest.mark.asyncio
async def test_check_email_exists_false(user_service):
    exists = await user_service.auth.check_email_exists(f"nonexistent_{uuid4().hex}@example.com")

    assert exists is False




@pytest.mark.asyncio
async def test_verify_password_correct(user_service, test_user):
    verified = await user_service.auth.verify_password(user_id=test_user.id, password="TestPassword123")

    assert verified is True


@pytest.mark.asyncio
async def test_verify_password_incorrect(user_service, test_user):
    verified = await user_service.auth.verify_password(user_id=test_user.id, password="WrongPassword")

    assert verified is False




@pytest.mark.asyncio
async def test_get_field_priority_config_custom(user_service, test_user, db_session):
    from giljo_mcp.models.auth import UserFieldPriority

    for cat, enabled in [("tech_stack", True), ("git_history", True), ("testing", False)]:
        db_session.add(
            UserFieldPriority(
                user_id=test_user.id,
                tenant_key=test_user.tenant_key,
                category=cat,
                enabled=enabled,
            )
        )
    await db_session.commit()

    config = await user_service.get_field_priority_config(test_user.id)

    assert isinstance(config, dict)
    assert config["version"] == "4.0"
    assert config["priorities"]["tech_stack"]["toggle"] is True
    assert config["priorities"]["git_history"]["toggle"] is True
    assert config["priorities"]["testing"]["toggle"] is False
    assert config["priorities"]["product_core"]["toggle"] is True
    assert config["priorities"]["project_description"]["toggle"] is True


@pytest.mark.asyncio
async def test_get_field_priority_config_defaults(user_service, test_user):
    config = await user_service.get_field_priority_config(test_user.id)

    assert isinstance(config, dict)
    assert config["version"] in ["3.0", "4.0"]
    assert "priorities" in config
    assert config["priorities"]["git_history"]["toggle"] is False




@pytest.mark.asyncio
async def test_update_field_priority_config_success(user_service, test_user, db_session):
    new_config = {
        "version": "4.0",
        "priorities": {
            "vision_documents": {"toggle": True},
            "agent_templates": {"toggle": False},
            "git_history": {"toggle": True},
        },
    }

    result = await user_service.update_field_priority_config(user_id=test_user.id, config=new_config)
    assert result is None

    config = await user_service.get_field_priority_config(test_user.id)
    assert config["priorities"]["vision_documents"]["toggle"] is True
    assert config["priorities"]["agent_templates"]["toggle"] is False
    assert config["priorities"]["git_history"]["toggle"] is True


@pytest.mark.asyncio
async def test_update_field_priority_config_validation(user_service, test_user):
    invalid_config = {
        "version": "4.0",
        "priorities": {
            "tech_stack": 5
        },
    }

    with pytest.raises(ValidationError) as exc_info:
        await user_service.update_field_priority_config(user_id=test_user.id, config=invalid_config)

    assert "invalid" in str(exc_info.value).lower()




@pytest.mark.asyncio
async def test_reset_field_priority_config_clears_custom(user_service, test_user, db_session):
    await user_service.update_field_priority_config(
        test_user.id,
        {
            "version": "4.0",
            "priorities": {"tech_stack": {"toggle": False}, "git_history": {"toggle": True}},
        },
    )

    result = await user_service.reset_field_priority_config(test_user.id)
    assert result is None

    config = await user_service.get_field_priority_config(test_user.id)
    assert config["priorities"]["git_history"]["toggle"] is False




@pytest.mark.asyncio
async def test_get_depth_config_custom(user_service, test_user, db_session):
    test_user.depth_vision_documents = "full"
    test_user.depth_memory_last_n = 5
    test_user.depth_git_commits = 50
    await db_session.commit()

    config = await user_service.get_depth_config(test_user.id)

    assert isinstance(config, dict)
    assert config["vision_documents"] == "full"
    assert config["memory_last_n_projects"] == 5
    assert config["git_commits"] == 50


@pytest.mark.asyncio
async def test_get_depth_config_defaults(user_service, test_user):
    config = await user_service.get_depth_config(test_user.id)

    assert isinstance(config, dict)
    assert config["vision_documents"] == "medium"
    assert config["memory_last_n_projects"] == 3
    assert config["git_commits"] == 25
    assert config["agent_templates"] == "basic"




@pytest.mark.asyncio
async def test_update_depth_config_success(user_service, test_user, db_session):
    new_depth = {"vision_documents": "full", "memory_last_n_projects": 10, "git_commits": 100}

    result = await user_service.update_depth_config(user_id=test_user.id, config=new_depth)
    assert result is None

    await db_session.refresh(test_user)
    assert test_user.depth_vision_documents == "full"
    assert test_user.depth_memory_last_n == 10
    assert test_user.depth_git_commits == 100


@pytest.mark.asyncio
async def test_update_depth_config_validation(user_service, test_user):
    invalid_depth = {
        "vision_documents": "invalid_level"
    }

    with pytest.raises(ValidationError) as exc_info:
        await user_service.update_depth_config(user_id=test_user.id, config=invalid_depth)

    assert "invalid" in str(exc_info.value).lower()




@pytest.mark.asyncio
async def test_user_service_logging(user_service, test_user, caplog):
    import logging

    caplog.set_level(logging.INFO)

    await user_service.get_user(test_user.id)

    assert any("user" in record.message.lower() for record in caplog.records)
