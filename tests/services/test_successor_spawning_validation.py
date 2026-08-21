# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Successor Spawning Tests - Validation and Result Retrieval

Split from test_successor_spawning.py (Handover 0497e).

Validates:
3. predecessor_job_id validated: must exist, same project, same tenant
5. get_agent_result MCP tool returns stored result with tenant isolation
"""

import random
import uuid
from datetime import UTC

import pytest

from giljo_mcp.models import Product, Project


# Fixtures `tenant_key`, `agent_templates`, `project`, `service`,
# `other_tenant_key`, `other_tenant_templates`, `other_project`,
# and helper `_spawn_and_complete` are provided by tests/services/conftest.py.


# ============================================================================
# Test 3: Predecessor validation - existence
# ============================================================================


@pytest.mark.asyncio
class TestPredecessorValidation:
    """Verify predecessor_job_id validation."""

    async def test_nonexistent_predecessor_raises_error(self, service, project, tenant_key):
        """Spawning with a non-existent predecessor_job_id should raise ResourceNotFoundError."""
        from giljo_mcp.exceptions import ResourceNotFoundError

        with pytest.raises(ResourceNotFoundError, match="Predecessor job"):
            await service.spawn_job(
                agent_display_name="successor",
                agent_name="specialist-1",
                mission="Fix issues",
                project_id=project.id,
                tenant_key=tenant_key,
                predecessor_job_id=str(uuid.uuid4()),  # Non-existent
            )

    async def test_predecessor_different_project_raises_error(self, db_session, service, project, tenant_key):
        """Predecessor from a different project should raise ValidationError."""
        from datetime import datetime

        from giljo_mcp.exceptions import ValidationError
        from tests.services.conftest import _spawn_and_complete

        # Create a second project in the same tenant (unique series_number to avoid uq_project_taxonomy)
        # BE-9437: a project belongs to a product. Its own, so an active
        # seed cannot collide under idx_project_single_active_per_product.
        _owning_product_proj2 = Product(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            name=f"Owning Product {uuid.uuid4().hex[:6]}",
            description="seeded",
            is_active=False,
        )
        db_session.add(_owning_product_proj2)
        proj2 = Project(
            id=str(uuid.uuid4()),
            name="Other Project",
            description="Different project",
            mission="Other work",
            status="active",
            tenant_key=tenant_key,
            product_id=_owning_product_proj2.id,
            execution_mode="multi_terminal",
            series_number=random.randint(1, 9000),
            implementation_launched_at=datetime.now(UTC),
        )
        db_session.add(proj2)
        await db_session.commit()

        # Spawn and complete predecessor in project2
        pred_spawn = await _spawn_and_complete(service, proj2.id, tenant_key, {"summary": "Done in other project"})

        # Try to spawn successor in project1 referencing project2's predecessor
        with pytest.raises(ValidationError, match="different project"):
            await service.spawn_job(
                agent_display_name="successor",
                agent_name="specialist-1",
                mission="Fix issues",
                project_id=project.id,
                tenant_key=tenant_key,
                predecessor_job_id=pred_spawn.job_id,
            )

    async def test_predecessor_different_tenant_raises_error(
        self, service, project, other_project, tenant_key, other_tenant_key
    ):
        """Predecessor from a different tenant should raise ResourceNotFoundError (not found in tenant scope)."""
        from giljo_mcp.exceptions import ResourceNotFoundError
        from tests.services.conftest import _spawn_and_complete

        # Spawn and complete in OTHER tenant
        pred_spawn = await _spawn_and_complete(
            service, other_project.id, other_tenant_key, {"summary": "Other tenant work"}
        )

        # Try to spawn successor referencing other tenant's predecessor
        with pytest.raises(ResourceNotFoundError, match="Predecessor job"):
            await service.spawn_job(
                agent_display_name="successor",
                agent_name="specialist-1",
                mission="Fix issues",
                project_id=project.id,
                tenant_key=tenant_key,
                predecessor_job_id=pred_spawn.job_id,
            )


# ============================================================================
# Test 5: get_agent_result tool returns stored result
# ============================================================================


@pytest.mark.asyncio
class TestGetAgentResultTool:
    """Verify get_agent_result via tool_accessor returns stored result."""

    async def test_returns_result_for_completed_job(self, service, project, tenant_key):
        """get_agent_result should return the result dict."""
        from tests.services.conftest import _spawn_and_complete

        result_payload = {
            "summary": "Auth module complete",
            "artifacts": ["src/auth.py"],
            "commits": ["abc123"],
        }
        pred_spawn = await _spawn_and_complete(service, project.id, tenant_key, result_payload)

        stored = await service.get_agent_result(
            job_id=pred_spawn.job_id,
            tenant_key=tenant_key,
        )

        assert stored is not None
        assert stored["summary"] == "Auth module complete"
        assert "abc123" in stored["commits"]

    async def test_returns_none_for_incomplete_job(self, service, project, tenant_key):
        """get_agent_result should return None for jobs not yet completed."""
        spawn = await service.spawn_job(
            agent_display_name="specialist",
            agent_name="specialist-1",
            mission="Still working",
            project_id=project.id,
            tenant_key=tenant_key,
        )

        stored = await service.get_agent_result(
            job_id=spawn.job_id,
            tenant_key=tenant_key,
        )

        assert stored is None

    async def test_tenant_isolation(self, service, project, other_project, tenant_key, other_tenant_key):
        """get_agent_result should NOT return results from other tenants."""
        from tests.services.conftest import _spawn_and_complete

        result_payload = {"summary": "Secret work", "commits": ["secret123"]}
        pred_spawn = await _spawn_and_complete(service, other_project.id, other_tenant_key, result_payload)

        # Try to read with wrong tenant key
        stored = await service.get_agent_result(
            job_id=pred_spawn.job_id,
            tenant_key=tenant_key,  # WRONG tenant
        )

        assert stored is None
