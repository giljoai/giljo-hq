# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
import uuid

import pytest
import pytest_asyncio

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project




@pytest_asyncio.fixture
async def test_tenant_0367a() -> str:
    return f"tk_0367a_{uuid.uuid4().hex[:12]}"


@pytest_asyncio.fixture
async def test_project_0367a(db_session, test_tenant_0367a) -> Project:
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=test_tenant_0367a,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name="0367a MCPAgentJob Removal Test",
        description="Test project for MCPAgentJob removal migration",
        mission="Test the removal of MCPAgentJob from service layer",
        status="active",
        tenant_key=test_tenant_0367a,
        product_id=_owning_product_project.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def test_agent_job_0367a(db_session, test_project_0367a, test_tenant_0367a) -> AgentJob:
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=test_tenant_0367a,
        project_id=test_project_0367a.id,
        mission="Test mission for 0367a",
        job_type="orchestrator",
        status="active",
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job


@pytest_asyncio.fixture
async def test_agent_execution_0367a(db_session, test_agent_job_0367a, test_tenant_0367a) -> AgentExecution:
    execution = AgentExecution(
        agent_id=str(uuid.uuid4()),
        job_id=test_agent_job_0367a.job_id,
        tenant_key=test_tenant_0367a,
        agent_display_name="orchestrator",
        agent_name="Orchestrator #1",
        status="working",
        progress=50,
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
    )
    db_session.add(execution)
    await db_session.commit()
    await db_session.refresh(execution)
    return execution




@pytest.mark.asyncio
class TestOrchestrationServiceNoFallback:

    async def test_complete_job_returns_error_when_execution_not_found(self, db_session, db_manager, test_tenant_0367a):
        from giljo_mcp.exceptions import ResourceNotFoundError
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        fake_job_id = str(uuid.uuid4())
        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.complete_job(
                job_id=fake_job_id,
                result={"output": "test"},
                tenant_key=test_tenant_0367a,
            )

        assert "not found" in str(exc_info.value).lower() or "no active execution" in str(exc_info.value).lower()

    async def test_complete_job_uses_only_agent_execution(
        self, db_session, db_manager, test_agent_execution_0367a, test_agent_job_0367a, test_tenant_0367a
    ):
        from giljo_mcp.services.orchestration_service import OrchestrationService
        from giljo_mcp.tenant import TenantManager

        tenant_manager = TenantManager()
        service = OrchestrationService(db_manager=db_manager, tenant_manager=tenant_manager, test_session=db_session)

        result = await service.complete_job(
            job_id=test_agent_job_0367a.job_id,
            result={"output": "test"},
            tenant_key=test_tenant_0367a,
        )

        assert result.status == "success"

        await db_session.refresh(test_agent_execution_0367a)
        assert test_agent_execution_0367a.status in ["complete", "decommissioned", "blocked"]









class TestNoMCPAgentJobImport:

    def test_orchestration_service_no_mcpagentjob_import(self):
        import ast
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        file_path = repo_root / "src" / "giljo_mcp" / "services" / "orchestration_service.py"
        assert file_path.exists(), f"Expected source file not found: {file_path}"

        with open(file_path, encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)

        mcp_agent_job_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.names:
                    for alias in node.names:
                        if alias.name == "MCPAgentJob":
                            mcp_agent_job_imports.append(f"from {node.module} import MCPAgentJob")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "MCPAgentJob" in alias.name:
                        mcp_agent_job_imports.append(f"import {alias.name}")

        assert len(mcp_agent_job_imports) == 0, (
            f"OrchestrationService still imports MCPAgentJob: {mcp_agent_job_imports}"
        )

    def test_project_service_no_mcpagentjob_import(self):
        import ast
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        package_dir = repo_root / "src" / "giljo_mcp" / "services" / "project_service"
        assert package_dir.is_dir(), f"Expected source package not found: {package_dir}"

        mcp_agent_job_imports = []
        for file_path in sorted(package_dir.glob("*.py")):
            with open(file_path, encoding="utf-8") as f:
                source = f.read()

            tree = ast.parse(source)

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.names:
                    for alias in node.names:
                        if alias.name == "MCPAgentJob":
                            mcp_agent_job_imports.append(f"{file_path.name}: from {node.module} import MCPAgentJob")

        assert len(mcp_agent_job_imports) == 0, f"ProjectService still imports MCPAgentJob: {mcp_agent_job_imports}"

