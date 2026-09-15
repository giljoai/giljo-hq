# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.auth import User, UserFieldPriority
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.user_service import UserService




@pytest_asyncio.fixture
async def test_tenant_key():
    return f"test_tenant_{uuid4().hex[:8]}"


@pytest_asyncio.fixture
async def test_organization(db_session, test_tenant_key):
    org = Organization(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        name=f"Test Org {test_tenant_key}",
        slug=f"test-org-{test_tenant_key.replace('_', '-')}",
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def user_service(db_manager, db_session, test_tenant_key):
    return UserService(
        db_manager=db_manager,
        tenant_key=test_tenant_key,
        websocket_manager=None,
        session=db_session,
    )


@pytest_asyncio.fixture
async def test_user(db_session, test_tenant_key, test_organization):
    user = User(
        id=str(uuid4()),
        username=f"testuser_{uuid4().hex[:6]}",
        email=f"test_{uuid4().hex[:6]}@example.com",
        password_hash="hashed_password",
        full_name="Test User",
        role="developer",
        tenant_key=test_tenant_key,
        org_id=test_organization.id,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def user_with_toggles(db_session, test_tenant_key, test_organization):
    user = User(
        id=str(uuid4()),
        username=f"configuser_{uuid4().hex[:6]}",
        email=f"config_{uuid4().hex[:6]}@example.com",
        password_hash="hashed_password",
        full_name="Configured User",
        role="developer",
        tenant_key=test_tenant_key,
        org_id=test_organization.id,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    for cat, enabled in [
        ("tech_stack", True),
        ("architecture", True),
        ("testing", True),
        ("vision_documents", True),
        ("memory_360", True),
        ("agent_templates", True),
        ("git_history", False),
    ]:
        db_session.add(
            UserFieldPriority(
                user_id=user.id,
                tenant_key=test_tenant_key,
                category=cat,
                enabled=enabled,
            )
        )

    await db_session.commit()
    await db_session.refresh(user)
    return user




@pytest.mark.asyncio
async def test_field_toggles_persist_via_update(user_service, test_user, db_session):
    new_config = {
        "version": "4.0",
        "priorities": {
            "tech_stack": {"toggle": True},
            "vision_documents": {"toggle": True},
            "agent_templates": {"toggle": True},
            "memory_360": {"toggle": True},
            "git_history": {"toggle": False},
        },
    }

    await user_service.update_field_priority_config(user_id=test_user.id, config=new_config)

    from sqlalchemy import and_, select

    stmt = select(UserFieldPriority).where(
        and_(UserFieldPriority.user_id == test_user.id, UserFieldPriority.tenant_key == test_user.tenant_key)
    )
    result = await db_session.execute(stmt)
    rows = {r.category: r.enabled for r in result.scalars().all()}

    assert rows["tech_stack"] is True
    assert rows["git_history"] is False
    assert rows["vision_documents"] is True


@pytest.mark.asyncio
async def test_field_toggles_retrieved_with_correct_structure(user_service, user_with_toggles, db_session):
    config = await user_service.get_field_priority_config(user_with_toggles.id)

    assert isinstance(config, dict), "Config should be a dictionary"
    assert "priorities" in config
    assert "fields" not in config

    assert config["priorities"]["product_core"]["toggle"] is True
    assert config["priorities"]["project_description"]["toggle"] is True

    assert config["priorities"]["git_history"]["toggle"] is False
    assert config["priorities"]["tech_stack"]["toggle"] is True


@pytest.mark.asyncio
async def test_default_field_toggles_use_priorities_key(user_service, test_user):
    config = await user_service.get_field_priority_config(test_user.id)

    assert isinstance(config, dict)
    assert "priorities" in config

    priorities = config["priorities"]
    assert isinstance(priorities, dict)
    assert len(priorities) > 0

    for category, toggle_config in priorities.items():
        if isinstance(toggle_config, dict):
            assert "toggle" in toggle_config
            assert isinstance(toggle_config["toggle"], bool)
        elif isinstance(toggle_config, bool):
            pass
        else:
            pytest.fail(f"Invalid toggle format for '{category}': {toggle_config}")


@pytest.mark.asyncio
async def test_field_toggles_version_is_4_0(user_service, test_user):
    new_config = {
        "version": "4.0",
        "priorities": {
            "tech_stack": {"toggle": True},
            "vision_documents": {"toggle": True},
            "agent_templates": {"toggle": False},
        },
    }

    await user_service.update_field_priority_config(user_id=test_user.id, config=new_config)

    config = await user_service.get_field_priority_config(test_user.id)
    assert config["version"] == "4.0"




@pytest.mark.asyncio
async def test_field_toggles_handles_no_rows_gracefully(user_service, test_user, db_session):
    config = await user_service.get_field_priority_config(test_user.id)

    assert isinstance(config, dict)
    assert "priorities" in config
    assert config["priorities"]["git_history"]["toggle"] is False


@pytest.mark.asyncio
async def test_field_toggles_validates_structure(user_service, test_user):
    invalid_config = {
        "version": "4.0",
        "priorities": {
            "tech_stack": 5,
        },
    }

    with pytest.raises(ValidationError) as exc_info:
        await user_service.update_field_priority_config(user_id=test_user.id, config=invalid_config)

    assert "invalid" in str(exc_info.value).lower()
