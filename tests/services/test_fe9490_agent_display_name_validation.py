# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import AgentJob, AgentTemplate, Product, Project
from giljo_mcp.services.agent_job_manager import AgentJobManager
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService
from giljo_mcp.utils.identity import validate_agent_display_name
from tests.helpers.product_crew_helper import adopt_all_templates






class TestValidateAgentDisplayName:
    def test_parenthetical_name_is_refused(self):
        with pytest.raises(ValidationError, match="punctuation"):
            validate_agent_display_name("Reviewer (Phase 5)")

    @pytest.mark.parametrize(
        "bad_char_name",
        ["Reviewer:Phase5", "Reviewer/Phase5", "Reviewer;Phase5", 'Reviewer"5"', "Reviewer#5"],
    )
    def test_other_punctuation_is_also_refused(self, bad_char_name):
        with pytest.raises(ValidationError):
            validate_agent_display_name(bad_char_name)

    @pytest.mark.parametrize(
        "clean_name",
        ["orchestrator", "Backend-Implementer", "Reviewer 2", "reviewer_2", "Reviewer-2"],
    )
    def test_letters_digits_space_hyphen_underscore_are_allowed(self, clean_name):
        assert validate_agent_display_name(clean_name) == clean_name

    def test_surrounding_whitespace_is_trimmed(self):
        assert validate_agent_display_name("  Reviewer  ") == "Reviewer"

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_blank_is_refused(self, blank):
        with pytest.raises(ValidationError):
            validate_agent_display_name(blank)

    def test_non_string_is_refused(self):
        with pytest.raises(ValidationError):
            validate_agent_display_name(12345)  # type: ignore[arg-type]

    def test_over_length_is_refused(self):
        with pytest.raises(ValidationError):
            validate_agent_display_name("a" * 129)




@pytest_asyncio.fixture
async def fe9490_project(db_session, test_tenant_key) -> Project:
    owning_product = Product(
        id=str(uuid.uuid4()),
        tenant_key=test_tenant_key,
        name=f"FE-9490 Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(owning_product)

    project = Project(
        id=str(uuid.uuid4()),
        name="FE-9490 Display Name Boundary",
        description="Agent display name punctuation-rejection boundary test.",
        mission="Spawn agents with clean and punctuated names.",
        status="active",
        tenant_key=test_tenant_key,
        product_id=owning_product.id,
        execution_mode="multi_terminal",
        series_number=random.randint(1, 9000),
        created_at=datetime.now(UTC),
    )
    db_session.add(project)

    db_session.add(
        AgentTemplate(
            id=str(uuid.uuid4()),
            tenant_key=test_tenant_key,
            name="implementer",
            is_active=True,
        )
    )
    db_session.info["tenant_key"] = test_tenant_key
    await db_session.commit()
    await db_session.refresh(project)
    await adopt_all_templates(db_session, test_tenant_key, owning_product.id)
    return project




@pytest.mark.asyncio
class TestSpawnJobRejectsPunctuation:
    async def test_parenthetical_display_name_is_refused_on_create(
        self, db_manager, db_session, tenant_manager, test_tenant_key, fe9490_project
    ):
        service = JobLifecycleService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        with pytest.raises(ValidationError, match="punctuation"):
            await service.spawn_job(
                agent_display_name="Reviewer (Phase 5)",
                agent_name="implementer",
                project_id=fe9490_project.id,
                tenant_key=test_tenant_key,
                mission="Review phase 5",
            )

        rows = (
            (await db_session.execute(select(AgentJob).where(AgentJob.tenant_key == test_tenant_key))).scalars().all()
        )
        assert rows == [], "A refused spawn must not leave a row behind."

    async def test_clean_display_name_still_spawns(
        self, db_manager, db_session, tenant_manager, test_tenant_key, fe9490_project
    ):
        service = JobLifecycleService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.spawn_job(
            agent_display_name="Backend Implementer",
            agent_name="implementer",
            project_id=fe9490_project.id,
            tenant_key=test_tenant_key,
            mission="Implement feature X",
        )

        assert result.job_id
        assert result.agent_display_name == "Backend Implementer"




@pytest.mark.asyncio
class TestSpawnExecutionRejectsPunctuation:
    async def test_parenthetical_display_name_is_refused_on_succession(
        self, db_manager, db_session, tenant_manager, test_tenant_key, fe9490_project
    ):
        job_service = JobLifecycleService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)
        first = await job_service.spawn_job(
            agent_display_name="Implementer",
            agent_name="implementer",
            project_id=fe9490_project.id,
            tenant_key=test_tenant_key,
            mission="Implement feature X",
        )

        agent_manager = AgentJobManager(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        with pytest.raises(ValidationError, match="punctuation"):
            await agent_manager.spawn_execution(
                job_id=first.job_id,
                agent_display_name="Implementer (Retry)",
                tenant_key=test_tenant_key,
            )

    async def test_clean_display_name_still_spawns_a_successor(
        self, db_manager, db_session, tenant_manager, test_tenant_key, fe9490_project
    ):
        job_service = JobLifecycleService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)
        first = await job_service.spawn_job(
            agent_display_name="Implementer",
            agent_name="implementer",
            project_id=fe9490_project.id,
            tenant_key=test_tenant_key,
            mission="Implement feature X",
        )

        agent_manager = AgentJobManager(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        job_id, agent_id = await agent_manager.spawn_execution(
            job_id=first.job_id,
            agent_display_name="Implementer Successor",
            tenant_key=test_tenant_key,
        )

        assert job_id == first.job_id
        assert agent_id
