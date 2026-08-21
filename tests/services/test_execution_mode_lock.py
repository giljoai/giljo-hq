# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for the execution_mode lock — retargeted to implementation LAUNCH.

execution_mode is a prompt-injection toggle resolved live by every downstream
reader (staging-prompt generation, get_staging_instructions, spawn_job,
get_agent_mission), so it stays freely changeable until the user LAUNCHES
implementation (implementation_launched_at is stamped by the Implement button /
orchestrator Play). Only after launch is it locked — changing it then would
desync agents already running with prompts rendered for the chosen mode.

This supersedes the Handover 0343 mission-based lock, which keyed on the wrong
signal ("mission exists") and wrongly froze staged-but-not-launched projects and
legacy rows born with a default mode.

BEHAVIOR TESTED:
- execution_mode can be changed before staging (no mission, not launched)
- execution_mode can STILL be changed after a mission exists but BEFORE launch
  (the staged-but-not-launched window — the BE-6059 regression fix)
- execution_mode CANNOT be changed once implementation_launched_at is set
- Setting the first mode on a NULL-mode project is always allowed pre-launch
- Other fields remain changeable regardless

Updated for Handover 0730: Exception-based patterns (no success wrapper)
"""

import random
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ProjectStateError
from giljo_mcp.models import Product, Project
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager


@pytest.mark.asyncio
async def test_update_execution_mode_allowed_before_staging(
    db_manager, db_session: AsyncSession, tenant_manager: TenantManager
):
    """
    GIVEN: A project with NO mission (staging not started)
    WHEN: Attempting to change execution_mode
    THEN: Should succeed
    """
    tenant_key = TenantManager.generate_tenant_key()
    tenant_manager.set_current_tenant(tenant_key)

    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        name="Pre-Staging Project",
        mission="",  # Empty - no staging
        description="Test description",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        status="inactive",
        execution_mode="multi_terminal",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    service = ProjectService(db_manager, tenant_manager, test_session=db_session)
    result = await service.update_project(project.id, {"execution_mode": "claude_code_cli"})

    assert result.execution_mode == "claude_code_cli"
    assert result.id == project.id


@pytest.mark.asyncio
async def test_update_execution_mode_allowed_when_staged_but_not_launched(
    db_manager, db_session: AsyncSession, tenant_manager: TenantManager
):
    """
    Regression (BE-6059): the staged-but-not-launched window must stay editable.

    GIVEN: A project that has been STAGED (mission generated, staging_status
           'staging_complete') carrying a legacy/default execution_mode, whose
           implementation has NOT launched (implementation_launched_at is None) —
           e.g. a row born 'multi_terminal' under the pre-NULL-state default.
    WHEN: The user switches the execution mode (multi_terminal -> claude_code_cli).
    THEN: It SUCCEEDS. The old mission-based lock wrongly froze this; a
          prompt-injection toggle must stay switchable until agents actually launch.
    """
    tenant_key = TenantManager.generate_tenant_key()
    tenant_manager.set_current_tenant(tenant_key)

    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        name="Staged Not Launched Project",
        mission="Orchestrator-generated mission from staging.",
        description="Test description",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        status="active",
        execution_mode="multi_terminal",  # legacy/default value never explicitly chosen
        staging_status="staging_complete",
        implementation_launched_at=None,  # not launched yet -> still editable
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    service = ProjectService(db_manager, tenant_manager, test_session=db_session)
    result = await service.update_project(project.id, {"execution_mode": "claude_code_cli"})

    assert result.execution_mode == "claude_code_cli"


@pytest.mark.asyncio
async def test_update_execution_mode_blocked_after_implementation_launched(
    db_manager, db_session: AsyncSession, tenant_manager: TenantManager
):
    """
    GIVEN: A project whose implementation has LAUNCHED (implementation_launched_at set)
    WHEN: Attempting to change execution_mode
    THEN: Should raise ProjectStateError — agents are live and prompts are already
          rendered for the chosen mode; switching now would desync them.
    """
    tenant_key = TenantManager.generate_tenant_key()
    tenant_manager.set_current_tenant(tenant_key)

    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        name="Launched Project",
        mission="This is the orchestrator-generated mission for the project.",
        description="Test description",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        status="active",
        execution_mode="claude_code_cli",
        implementation_launched_at=datetime.now(UTC),  # agents are live
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()

    service = ProjectService(db_manager, tenant_manager, test_session=db_session)

    with pytest.raises(ProjectStateError) as exc_info:
        await service.update_project(project.id, {"execution_mode": "multi_terminal"})

    error_msg = str(exc_info.value).lower()
    assert "launch" in error_msg or "implementation" in error_msg, (
        f"Expected error about implementation launch, got: {exc_info.value}"
    )


@pytest.mark.asyncio
async def test_update_other_fields_still_allowed_after_launch(
    db_manager, db_session: AsyncSession, tenant_manager: TenantManager
):
    """
    GIVEN: A project whose implementation has launched
    WHEN: Updating name or description (not execution_mode)
    THEN: Should succeed - only execution_mode is locked after launch
    """
    tenant_key = TenantManager.generate_tenant_key()
    tenant_manager.set_current_tenant(tenant_key)

    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        name="Locked Project",
        mission="Original generated mission",
        description="Original description",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        status="active",
        execution_mode="multi_terminal",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()

    service = ProjectService(db_manager, tenant_manager, test_session=db_session)
    result = await service.update_project(
        project.id,
        {
            "name": "Updated Name",
            "description": "Updated description",
        },
    )

    assert result.name == "Updated Name"
    assert result.description == "Updated description"
    assert result.execution_mode == "multi_terminal"  # unchanged


@pytest.mark.asyncio
async def test_set_first_mode_allowed_when_unselected_despite_mission(
    db_manager, db_session: AsyncSession, tenant_manager: TenantManager
):
    """
    NULL-state carve-out (now subsumed by the launch-based lock, still valid).

    GIVEN: A project born with a mission but NO chosen execution_mode (NULL) and
           not launched — e.g. a CTX-bootstrap project that renders its mission at
           creation.
    WHEN: Setting the FIRST execution_mode.
    THEN: It is ALLOWED (pre-launch changes are always permitted, NULL or not).
    """
    tenant_key = TenantManager.generate_tenant_key()
    tenant_manager.set_current_tenant(tenant_key)

    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        name="CTX-like Project",
        mission="A bootstrap mission rendered at creation.",  # mission exists...
        description="Test description",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        status="inactive",
        execution_mode=None,  # ...but no mode chosen yet
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    service = ProjectService(db_manager, tenant_manager, test_session=db_session)
    result = await service.update_project(project.id, {"execution_mode": "claude_code_cli"})

    assert result.execution_mode == "claude_code_cli"
