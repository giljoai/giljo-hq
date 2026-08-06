# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-3006a single-writer rule — staging-state write owned by the service.

The REST staging endpoint (``api/endpoints/prompts.py``) used to raw-write
``project.staging_status='staged'`` + ``execution_mode`` and ``db.commit()``.
That write now lives in ``ProjectStagingService.mark_staged`` (a twin of
restage/unstage), reached from the endpoint via the lifecycle facade.

These tests exercise the service directly: the staged-state + mode persist, the
implementation_launched_at lock on execution_mode is honoured, and a missing
project raises.

The mark_staged single-writer transaction fix: ``mark_staged`` now also
accepts an explicit ``tenant_key`` + caller-supplied ``db_session`` so it can
run on the SAME session as ``stage()``'s prompt generation (previously it
always opened a second, independent session — the two-session split this
fix closes). The three tests below cover the new signature at the SERVICE
layer; the MCP-boundary counterpart lives in
``tests/integration/test_inf6049b_stage_implement_tools.py``.
"""

import random
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models import Project
from giljo_mcp.models.products import Product
from giljo_mcp.services.project_staging_service import ProjectStagingService


@pytest.fixture
def staging_service(db_session, test_tenant_key):
    """ProjectStagingService backed by the test session (mirrors the existing suite)."""
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    return ProjectStagingService(
        db_manager=MagicMock(),
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


async def _seed_product(session, tenant_key):
    """TSK-8005: seed a real Product instead of relying on projects.product_id=NULL
    (production enforces NOT NULL via ce_0004; NULL also risks a
    uq_project_taxonomy_active NULLS-NOT-DISTINCT collision within a tenant)."""
    product = Product(id=str(uuid.uuid4()), tenant_key=tenant_key, name="Mark-Staged Test Product")
    session.add(product)
    await session.flush()
    return product


async def _seed_project(session, tenant_key, *, staging_status="staging", launched=False, execution_mode=None):
    """Seed a project as the generator leaves it (staging_status='staging')."""
    product = await _seed_product(session, tenant_key)
    project = Project(
        tenant_key=tenant_key,
        product_id=product.id,
        name="Mark-Staged Project",
        description="seeded",
        mission="seeded mission",
        status=ProjectStatus.INACTIVE,
        staging_status=staging_status,
        execution_mode=execution_mode,
        implementation_launched_at=datetime.now(UTC) if launched else None,
        series_number=random.randint(1, 9000),
    )
    session.add(project)
    await session.flush()
    return project


@pytest.mark.asyncio
async def test_mark_staged_persists_staged_and_mode(staging_service, db_session, test_tenant_key):
    """mark_staged flips 'staging' -> 'staged' and writes the resolved mode."""
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, execution_mode=None)

    await staging_service.mark_staged(str(project.id), "claude_code_cli")

    assert project.staging_status == "staged"
    assert project.execution_mode == "claude_code_cli"


@pytest.mark.asyncio
async def test_mark_staged_respects_launch_lock(staging_service, db_session, test_tenant_key):
    """Once implementation has launched, mark_staged must NOT rewrite execution_mode."""
    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, launched=True, execution_mode="multi_terminal")

    await staging_service.mark_staged(str(project.id), "claude_code_cli")

    assert project.staging_status == "staged"
    # Locked: the original mode survives.
    assert project.execution_mode == "multi_terminal"


@pytest.mark.asyncio
async def test_mark_staged_raises_for_missing_project(staging_service):
    """A non-existent project id raises ResourceNotFoundError (maps to 404)."""
    with pytest.raises(ResourceNotFoundError):
        await staging_service.mark_staged("00000000-0000-0000-0000-000000000000", "multi_terminal")


@pytest.mark.asyncio
async def test_mark_staged_accepts_caller_session_and_explicit_tenant(db_session, test_tenant_key):
    """A caller-supplied db_session + tenant_key must be used AS-IS — no second session.

    ``db_manager.get_session_async`` is wired to raise if it is ever invoked, so a
    passing test proves ``mark_staged`` never opens its own session when one is
    injected. Fails against today's code with a TypeError (no such kwargs exist yet).
    """
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    db_manager = MagicMock()
    db_manager.get_session_async.side_effect = AssertionError("must not open a new session")
    staging_service = ProjectStagingService(db_manager=db_manager, tenant_manager=tenant_manager)

    with tenant_session_context(db_session, test_tenant_key):
        project = await _seed_project(db_session, test_tenant_key, execution_mode=None)

        # Mirrors production: the caller (MCP dispatch / REST auth middleware)
        # already established ambient tenant context for the whole request BEFORE
        # handing this session to mark_staged -- this is the SAME session that
        # context is already live on, not a bare, context-free session.
        await staging_service.mark_staged(
            str(project.id), "claude_code_cli", tenant_key=test_tenant_key, db_session=db_session
        )

    assert project.staging_status == "staged"
    assert project.execution_mode == "claude_code_cli"
    db_manager.get_session_async.assert_not_called()


@pytest.mark.asyncio
async def test_mark_staged_raises_for_missing_project_with_caller_session(db_session, test_tenant_key):
    """The caller-session branch preserves the existing raise semantics for a missing project."""
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = test_tenant_key
    staging_service = ProjectStagingService(db_manager=MagicMock(), tenant_manager=tenant_manager)

    with tenant_session_context(db_session, test_tenant_key), pytest.raises(ResourceNotFoundError):
        await staging_service.mark_staged(
            "00000000-0000-0000-0000-000000000000",
            "multi_terminal",
            tenant_key=test_tenant_key,
            db_session=db_session,
        )


@pytest.mark.asyncio
async def test_mark_staged_no_tenant_available_raises_validation_error():
    """No tenant_key argument AND no resolvable contextvar must raise ValidationError.

    Fails against today's code because there is no tenant-missing guard at all --
    it would instead call the repository with tenant_key=None and hit whatever
    behavior that produces, which is the WRONG error for "no tenant resolved".
    """
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = None
    staging_service = ProjectStagingService(db_manager=MagicMock(), tenant_manager=tenant_manager)

    with pytest.raises(ValidationError):
        await staging_service.mark_staged(str(uuid.uuid4()), "multi_terminal")
