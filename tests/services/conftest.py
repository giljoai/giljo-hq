# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import bcrypt
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import AgentTemplate, Message
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.auth import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product, VisionDocument
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Task
from giljo_mcp.services.task_service import TaskService
from giljo_mcp.tenant import TenantManager
from tests.helpers.product_crew_helper import adopt_all_templates


async def _seed_owning_product(session, tenant_key, label):
    product = Product(
        id=str(uuid4()),
        name=f"{label} Product {uuid4().hex[:6]}",
        description="Owning product for a project fixture",
        tenant_key=tenant_key,
        is_active=False,
    )
    session.add(product)
    await session.flush()
    await adopt_all_templates(session, tenant_key, product.id)
    return product


@pytest_asyncio.fixture
async def user_service(db_manager, db_session, test_tenant_key):
    from giljo_mcp.services.user_service import UserService

    return UserService(
        db_manager=db_manager,
        tenant_key=test_tenant_key,
        websocket_manager=None,
        session=db_session,
    )


@pytest_asyncio.fixture
async def test_user(db_session, test_tenant_key):
    user = User(
        id=str(uuid4()),
        username=f"testuser_{uuid4().hex[:6]}",
        email=f"test_{uuid4().hex[:6]}@example.com",
        password_hash=bcrypt.hashpw(b"TestPassword123", bcrypt.gensalt()).decode("utf-8"),
        full_name="Test User",
        role="developer",
        tenant_key=test_tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def admin_user(db_session, test_tenant_key):
    admin = User(
        id=str(uuid4()),
        username=f"admin_{uuid4().hex[:6]}",
        email=f"admin_{uuid4().hex[:6]}@example.com",
        password_hash=bcrypt.hashpw(b"AdminPassword123", bcrypt.gensalt()).decode("utf-8"),
        full_name="Admin User",
        role="admin",
        tenant_key=test_tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    return admin


@pytest_asyncio.fixture
async def other_tenant_key():
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def test_product(db_session, test_tenant_key):
    product = Product(
        id=str(uuid4()),
        name=f"Test Product {uuid4().hex[:6]}",
        description="Test product for task service tests",
        tenant_key=test_tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


@pytest_asyncio.fixture
async def other_tenant_user(db_session, other_tenant_key):
    user = User(
        id=str(uuid4()),
        username=f"otheruser_{uuid4().hex[:6]}",
        email=f"other_{uuid4().hex[:6]}@example.com",
        password_hash=bcrypt.hashpw(b"OtherPassword123", bcrypt.gensalt()).decode("utf-8"),
        full_name="Other Tenant User",
        role="developer",
        tenant_key=other_tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def other_tenant_product(db_session, other_tenant_key):
    product = Product(
        id=str(uuid4()),
        name=f"Other Product {uuid4().hex[:6]}",
        description="Product for other tenant",
        tenant_key=other_tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


@pytest_asyncio.fixture
async def other_tenant_task(db_session, other_tenant_key, other_tenant_product, other_tenant_user):
    task = Task(
        id=str(uuid4()),
        tenant_key=other_tenant_key,
        product_id=other_tenant_product.id,
        title="Other Tenant Task",
        description="Task in different tenant",
        status="waiting",
        priority="medium",
        created_by_user_id=other_tenant_user.id,
        created_at=datetime.now(UTC),
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


@pytest_asyncio.fixture
async def task_service(db_manager, db_session, test_tenant_key):
    mock_tenant_manager = MagicMock()
    mock_tenant_manager.get_current_tenant.return_value = test_tenant_key

    return TaskService(
        db_manager=db_manager,
        tenant_manager=mock_tenant_manager,
        session=db_session,
    )




@pytest_asyncio.fixture
async def test_agent_templates(db_session, test_tenant_key):
    template_names = ["analyzer-1", "impl-1", "tester-1"]
    for name in template_names:
        template = AgentTemplate(
            tenant_key=test_tenant_key,
            name=name,
            role=name,
            description=f"Test template for {name}",
            system_instructions=f"# {name}\nTest agent instructions.",
            is_active=True,
        )
        db_session.add(template)
    await db_session.commit()


@pytest_asyncio.fixture
async def test_project(db_session, test_tenant_key, test_agent_templates) -> Project:
    _owning_product_project = await _seed_owning_product(db_session, test_tenant_key, "Phase")
    project = Project(
        id=str(uuid4()),
        name="Phase Labels Test Project",
        description="Test project for phase labels",
        mission="Test mission for phase labels",
        status="active",
        tenant_key=test_tenant_key,
        product_id=_owning_product_project.id,
        execution_mode="multi_terminal",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def test_project_multi_terminal(db_session, test_tenant_key, test_agent_templates) -> Project:
    _owning_product_project = await _seed_owning_product(db_session, test_tenant_key, "Multi")
    project = Project(
        id=str(uuid4()),
        name="Multi Terminal Phase Test",
        description="Test project for multi-terminal phase labels",
        mission="Test mission for multi-terminal",
        status="active",
        tenant_key=test_tenant_key,
        product_id=_owning_product_project.id,
        execution_mode="multi_terminal",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def test_project_cli_mode(db_session, test_tenant_key, test_agent_templates) -> Project:
    _owning_product_project = await _seed_owning_product(db_session, test_tenant_key, "CLI")
    project = Project(
        id=str(uuid4()),
        name="CLI Mode Phase Test",
        description="Test project for CLI mode",
        mission="Test mission for CLI mode",
        status="active",
        tenant_key=test_tenant_key,
        product_id=_owning_product_project.id,
        execution_mode="claude_code_cli",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project






async def create_test_org(session: AsyncSession, tenant_key: str, unique_suffix: str) -> Organization:
    org = Organization(
        tenant_key=tenant_key,
        name=f"Test Org {unique_suffix}",
        slug=f"test-org-{unique_suffix}",
        is_active=True,
    )
    session.add(org)
    await session.flush()
    return org




@pytest_asyncio.fixture
async def mock_websocket_manager():
    mock = MagicMock()
    mock.broadcast_message_sent = AsyncMock()
    mock.broadcast_message_received = AsyncMock()
    mock.broadcast_message_acknowledged = AsyncMock()
    mock.broadcast_job_message = AsyncMock()
    return mock






@pytest_asyncio.fixture(scope="function")
async def two_tenant_products(db_session, db_manager):
    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()

    product_a = Product(
        id=str(uuid4()),
        name="Tenant A Product",
        description="Product for tenant A",
        tenant_key=tenant_a,
        is_active=True,
        quality_standards="TDD required",
    )
    product_b = Product(
        id=str(uuid4()),
        name="Tenant B Product",
        description="Product for tenant B",
        tenant_key=tenant_b,
        is_active=True,
        quality_standards="Code review required",
    )
    db_session.add(product_a)
    db_session.add(product_b)
    await db_session.commit()

    project_a = Project(
        id=str(uuid4()),
        name="Tenant A Project",
        description="Project for tenant A",
        mission="Tenant A mission",
        tenant_key=tenant_a,
        product_id=product_a.id,
        status="active",
        series_number=random.randint(1, 9000),
    )
    project_b = Project(
        id=str(uuid4()),
        name="Tenant B Project",
        description="Project for tenant B",
        mission="Tenant B mission",
        tenant_key=tenant_b,
        product_id=product_b.id,
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add_all([project_a, project_b])
    await db_session.commit()

    task_a = Task(
        id=str(uuid4()),
        title="Tenant A Task",
        description="Task for tenant A",
        tenant_key=tenant_a,
        product_id=product_a.id,
        project_id=project_a.id,
        status="pending",
    )
    task_b = Task(
        id=str(uuid4()),
        title="Tenant B Task",
        description="Task for tenant B",
        tenant_key=tenant_b,
        product_id=product_b.id,
        project_id=project_b.id,
        status="pending",
    )
    db_session.add_all([task_a, task_b])

    vision_a = VisionDocument(
        id=str(uuid4()),
        product_id=product_a.id,
        tenant_key=tenant_a,
        document_name="Tenant A Vision",
        document_type="vision",
        vision_document="Vision content for tenant A",
        storage_type="inline",
    )
    vision_b = VisionDocument(
        id=str(uuid4()),
        product_id=product_b.id,
        tenant_key=tenant_b,
        document_name="Tenant B Vision",
        document_type="vision",
        vision_document="Vision content for tenant B",
        storage_type="inline",
    )
    db_session.add_all([vision_a, vision_b])

    job_a = AgentJob(
        job_id=str(uuid4()),
        job_type="implementer",
        tenant_key=tenant_a,
        project_id=project_a.id,
        mission="Implement feature for tenant A",
        status="active",
        created_at=datetime.now(UTC),
    )
    job_b = AgentJob(
        job_id=str(uuid4()),
        job_type="tester",
        tenant_key=tenant_b,
        project_id=project_b.id,
        mission="Test feature for tenant B",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add_all([job_a, job_b])
    await db_session.commit()

    execution_a = AgentExecution(
        agent_id=str(uuid4()),
        job_id=job_a.job_id,
        tenant_key=tenant_a,
        agent_display_name="implementer",
        agent_name="implementer-a",
        status="working",
        started_at=datetime.now(UTC),
    )
    execution_b = AgentExecution(
        agent_id=str(uuid4()),
        job_id=job_b.job_id,
        tenant_key=tenant_b,
        agent_display_name="tester",
        agent_name="tester-b",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add_all([execution_a, execution_b])

    message_a = Message(
        id=str(uuid4()),
        content="Message for tenant A",
        tenant_key=tenant_a,
        project_id=project_a.id,
        created_at=datetime.now(UTC),
    )
    message_b = Message(
        id=str(uuid4()),
        content="Message for tenant B",
        tenant_key=tenant_b,
        project_id=project_b.id,
        created_at=datetime.now(UTC),
    )
    db_session.add_all([message_a, message_b])
    await db_session.commit()

    for obj in [
        product_a,
        product_b,
        project_a,
        project_b,
        task_a,
        task_b,
        vision_a,
        vision_b,
        job_a,
        job_b,
        execution_a,
        execution_b,
        message_a,
        message_b,
    ]:
        await db_session.refresh(obj)

    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "product_a": product_a,
        "product_b": product_b,
        "project_a": project_a,
        "project_b": project_b,
        "task_a": task_a,
        "task_b": task_b,
        "vision_a": vision_a,
        "vision_b": vision_b,
        "job_a": job_a,
        "job_b": job_b,
        "execution_a": execution_a,
        "execution_b": execution_b,
        "message_a": message_a,
        "message_b": message_b,
        "db_session": db_session,
        "db_manager": db_manager,
    }




@pytest_asyncio.fixture
async def template_service(db_manager, tenant_manager):
    from giljo_mcp.services.template_service import TemplateService

    return TemplateService(db_manager, tenant_manager)


@pytest_asyncio.fixture
async def sample_template(db_session, test_tenant_key, test_product):
    from giljo_mcp.models.templates import AgentTemplate

    template = AgentTemplate(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        name="test-analyzer",
        role="analyzer",
        category="custom",
        cli_tool="claude",
        background_color="#FF5733",
        description="Test analyzer agent",
        system_instructions="You are an analyzer agent.",
        is_active=True,
        is_default=False,
        version="1.0.0",
    )
    db_session.add(template)
    await db_session.commit()
    await db_session.refresh(template)
    return template




@pytest_asyncio.fixture(scope="function")
async def two_tenant_service_setup(db_session, db_manager):
    from giljo_mcp.services.project_service import ProjectService

    tenant_a = TenantManager.generate_tenant_key()
    tenant_b = TenantManager.generate_tenant_key()

    product_a = Product(
        id=str(uuid4()),
        name="Service Test Product A",
        description="Product for tenant A service testing",
        tenant_key=tenant_a,
        is_active=True,
    )
    db_session.add(product_a)

    product_b = Product(
        id=str(uuid4()),
        name="Service Test Product B",
        description="Product for tenant B service testing",
        tenant_key=tenant_b,
        is_active=True,
    )
    db_session.add(product_b)

    await db_session.commit()
    await db_session.refresh(product_a)
    await db_session.refresh(product_b)

    project_a = Project(
        id=str(uuid4()),
        name="Service Test Project A",
        description="Project for tenant A service testing",
        mission="Test mission A",
        tenant_key=tenant_a,
        product_id=product_a.id,
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project_a)

    project_b = Project(
        id=str(uuid4()),
        name="Service Test Project B",
        description="Project for tenant B service testing",
        mission="Test mission B",
        tenant_key=tenant_b,
        product_id=product_b.id,
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project_b)

    await db_session.commit()
    await db_session.refresh(project_a)
    await db_session.refresh(project_b)

    job_a = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_a,
        project_id=project_a.id,
        mission="Test orchestrator mission A",
        job_type="orchestrator",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job_a)

    job_b = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_b,
        project_id=project_b.id,
        mission="Test orchestrator mission B",
        job_type="orchestrator",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job_b)

    await db_session.commit()
    await db_session.refresh(job_a)
    await db_session.refresh(job_b)

    agent_job_a = AgentExecution(
        agent_id=str(uuid4()),
        job_id=job_a.job_id,
        tenant_key=tenant_a,
        agent_display_name="orchestrator",
        status="working",
    )
    db_session.add(agent_job_a)

    agent_job_b = AgentExecution(
        agent_id=str(uuid4()),
        job_id=job_b.job_id,
        tenant_key=tenant_b,
        agent_display_name="orchestrator",
        status="working",
    )
    db_session.add(agent_job_b)

    await db_session.commit()
    await db_session.refresh(agent_job_a)
    await db_session.refresh(agent_job_b)

    tenant_manager = TenantManager()

    project_service_a = ProjectService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )

    task_service_a = TaskService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        session=db_session,
    )

    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "product_a": product_a,
        "product_b": product_b,
        "project_a": project_a,
        "project_b": project_b,
        "job_a": job_a,
        "job_b": job_b,
        "agent_job_a": agent_job_a,
        "agent_job_b": agent_job_b,
        "project_service_a": project_service_a,
        "task_service_a": task_service_a,
        "db_manager": db_manager,
        "tenant_manager": tenant_manager,
    }




@pytest_asyncio.fixture
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def agent_templates(db_session, tenant_key):
    for name in ["specialist-1", "tdd-implementor", "orchestrator"]:
        template = AgentTemplate(
            tenant_key=tenant_key,
            name=name,
            role=name,
            description=f"Test template for {name}",
            system_instructions=f"# {name}\nTest agent.",
            is_active=True,
        )
        db_session.add(template)
    await db_session.commit()


@pytest_asyncio.fixture
async def other_tenant_templates(db_session, other_tenant_key):
    for name in ["specialist-1"]:
        template = AgentTemplate(
            tenant_key=other_tenant_key,
            name=name,
            role=name,
            description=f"Other tenant template for {name}",
            system_instructions=f"# {name}\nOther tenant agent.",
            is_active=True,
        )
        db_session.add(template)
    await db_session.commit()


@pytest_asyncio.fixture
async def project(db_session, tenant_key, agent_templates) -> Project:
    _owning_product_proj = await _seed_owning_product(db_session, tenant_key, "Successor")
    proj = Project(
        id=str(uuid4()),
        name="Successor Test Project",
        description="Test project for 0497e successor spawning",
        mission="Test recovery flow",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_proj.id,
        execution_mode="multi_terminal",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)
    return proj


@pytest_asyncio.fixture
async def other_project(db_session, other_tenant_key, other_tenant_templates) -> Project:
    _owning_product_proj = await _seed_owning_product(db_session, other_tenant_key, "Other")
    proj = Project(
        id=str(uuid4()),
        name="Other Tenant Project",
        description="Project in a different tenant",
        mission="Other tenant work",
        status="active",
        tenant_key=other_tenant_key,
        product_id=_owning_product_proj.id,
        execution_mode="multi_terminal",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)
    return proj


@pytest_asyncio.fixture
async def service(db_session, db_manager) -> "OrchestrationService":  # noqa: F821 — forward ref, imported inside body
    from giljo_mcp.services.orchestration_service import OrchestrationService

    tm = TenantManager()
    return OrchestrationService(
        db_manager=db_manager,
        tenant_manager=tm,
        test_session=db_session,
    )


async def _spawn_and_complete(service, project_id, tenant_key, result_payload, agent_name="specialist-1"):
    spawn = await service.spawn_job(
        agent_display_name="predecessor",
        agent_name=agent_name,
        mission="Do predecessor work",
        project_id=project_id,
        tenant_key=tenant_key,
    )
    await service.complete_job(
        job_id=spawn.job_id,
        result=result_payload,
        tenant_key=tenant_key,
    )
    return spawn


def generate_realistic_document(tokens: int) -> str:
    base_paragraphs = [
        "The GiljoAI Agent Orchestration system provides a sophisticated multi-agent framework for complex software development tasks. The orchestrator coordinates specialized agents including implementors, testers, analyzers, and deployment specialists. Each agent operates with context awareness and token budget management to ensure efficient use of available language model capacity.",
        "Vision documents serve as high-level architectural guidance for orchestrators during project initialization and execution phases. These documents describe the overall system goals, technical constraints, implementation strategies, and design patterns that guide agent decision-making throughout the development lifecycle. Proper vision documentation ensures consistency across project phases.",
        "The system architecture leverages FastAPI for backend services with PostgreSQL for persistent storage and multi-tenant isolation. Frontend components are built using Vue 3 with Vuetify for material design components. Real-time updates are handled through WebSocket connections that provide live status updates to the dashboard interface for monitoring agent execution progress.",
        "Context management is critical for efficient token usage in large language models. The system employs a two-dimensional prioritization model combining field priority with depth configuration. This enables agents to access essential information while staying within context budget limits. Priority levels range from critical to excluded, while depth levels control the amount of detail included for each context field.",
        "Multi-tenant isolation ensures secure separation of data across different users and organizations. Each tenant operates in a completely isolated environment with dedicated database partitions enforced through tenant_key filtering. Access controls prevent cross-tenant data leakage. This architecture supports enterprise deployments while maintaining strict data security and privacy requirements.",
        "Agent job management provides lifecycle control for spawned agents including creation, execution monitoring, cancellation, and handover coordination. The system tracks context usage and supports manual succession via UI or slash commands. Job status updates are broadcast through WebSocket events to enable real-time UI updates and orchestrator coordination across distributed agents.",
        "Testing strategy encompasses unit tests with pytest for service layer validation, integration tests for API endpoints and database operations, and end-to-end tests for complete workflow verification. Code coverage targets exceed 80 percent across all critical paths. Frontend testing uses Vitest for component tests and Cypress for browser-based integration testing of user workflows.",
        "Authentication implements JWT tokens with refresh token rotation for enhanced security. Password hashing uses bcrypt with configurable work factors. Rate limiting protects against brute force attacks on authentication endpoints. Recovery mechanisms include PIN-based password reset with expiration and rate limiting to prevent abuse while maintaining user accessibility for account recovery scenarios.",
    ]

    avg_chars = sum(len(p) for p in base_paragraphs) // len(base_paragraphs)
    tokens_per_paragraph = avg_chars // 4
    paragraphs_needed = max(1, tokens // tokens_per_paragraph)

    paragraphs = []
    for i in range(paragraphs_needed):
        para = base_paragraphs[i % len(base_paragraphs)]
        variant = para.replace("system", f"system-v{i % 10}")
        paragraphs.append(variant)

    return "\n\n".join(paragraphs)




@pytest_asyncio.fixture
async def auth_service(db_manager, db_session):
    from giljo_mcp.services.auth_service import AuthService

    return AuthService(
        db_manager=db_manager,
        websocket_manager=None,
        session=db_session,
    )


@pytest_asyncio.fixture
async def auth_test_org(db_session):
    unique_id = str(uuid4())[:8]
    org = Organization(
        id=str(uuid4()),
        tenant_key=f"test_tenant_{unique_id}",
        name=f"Test Organization {unique_id}",
        slug=f"test-org-{unique_id}",
        is_active=True,
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest_asyncio.fixture
async def auth_user_with_password(db_session, auth_test_org):
    unique_id = str(uuid4())[:8]
    password = "Test1234!"
    user = User(
        id=str(uuid4()),
        username=f"testuser_{unique_id}",
        email=f"test_{unique_id}@example.com",
        full_name="Test User",
        password_hash=bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
        role="developer",
        tenant_key=auth_test_org.tenant_key,
        org_id=auth_test_org.id,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user, password
