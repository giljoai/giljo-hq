# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
import uuid
from datetime import UTC

import pytest

from giljo_mcp.models import Product, Project
from tests.helpers.product_crew_helper import adopt_all_templates






@pytest.mark.asyncio
class TestPredecessorValidation:

    async def test_nonexistent_predecessor_raises_error(self, service, project, tenant_key):
        from giljo_mcp.exceptions import ResourceNotFoundError

        with pytest.raises(ResourceNotFoundError, match="Predecessor job"):
            await service.spawn_job(
                agent_display_name="successor",
                agent_name="specialist-1",
                mission="Fix issues",
                project_id=project.id,
                tenant_key=tenant_key,
                predecessor_job_id=str(uuid.uuid4()),
            )

    async def test_predecessor_different_project_raises_error(self, db_session, service, project, tenant_key):
        from datetime import datetime

        from giljo_mcp.exceptions import ValidationError
        from tests.services.conftest import _spawn_and_complete

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
        await adopt_all_templates(db_session, tenant_key, _owning_product_proj2.id)

        pred_spawn = await _spawn_and_complete(service, proj2.id, tenant_key, {"summary": "Done in other project"})

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
        from giljo_mcp.exceptions import ResourceNotFoundError
        from tests.services.conftest import _spawn_and_complete

        pred_spawn = await _spawn_and_complete(
            service, other_project.id, other_tenant_key, {"summary": "Other tenant work"}
        )

        with pytest.raises(ResourceNotFoundError, match="Predecessor job"):
            await service.spawn_job(
                agent_display_name="successor",
                agent_name="specialist-1",
                mission="Fix issues",
                project_id=project.id,
                tenant_key=tenant_key,
                predecessor_job_id=pred_spawn.job_id,
            )




@pytest.mark.asyncio
class TestGetAgentResultTool:

    async def test_returns_result_for_completed_job(self, service, project, tenant_key):
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
        from tests.services.conftest import _spawn_and_complete

        result_payload = {"summary": "Secret work", "commits": ["secret123"]}
        pred_spawn = await _spawn_and_complete(service, other_project.id, other_tenant_key, result_payload)

        stored = await service.get_agent_result(
            job_id=pred_spawn.job_id,
            tenant_key=tenant_key,
        )

        assert stored is None
