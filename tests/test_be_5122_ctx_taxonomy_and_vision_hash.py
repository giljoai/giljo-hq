# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.ctx_bootstrap_template import (
    CTX_BOOTSTRAP_TEMPLATE,
    render_ctx_bootstrap,
)
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Product, TaxonomyType, VisionDocument
from giljo_mcp.services.mission_orchestration_service import MissionOrchestrationService
from giljo_mcp.services.taxonomy_ops import DEFAULT_TAXONOMY_TYPES
from giljo_mcp.services.vision_hash import (
    VISION_INPUTS_HASH_EMPTY,
    compute_vision_inputs_hash,
    vision_inputs_hash_matches_consolidated,
)
from giljo_mcp.tenant import TenantManager




def test_d1_default_taxonomy_includes_ctx() -> None:
    abbrs = [t["abbr"] for t in DEFAULT_TAXONOMY_TYPES]
    assert "CTX" in abbrs, "BE-5122: DEFAULT_TAXONOMY_TYPES must register CTX."
    ctx_entry = next(t for t in DEFAULT_TAXONOMY_TYPES if t["abbr"] == "CTX")
    assert ctx_entry["label"] == "Context Update"
    assert ctx_entry["color"].startswith("#")




class _FakeDoc:

    def __init__(
        self,
        doc_id: str,
        content: str,
        *,
        name: str = "Doc",
        is_active: bool = True,
        display_order: int = 0,
    ) -> None:
        self.id = doc_id
        self.vision_document = content
        self.document_name = name
        self.is_active = is_active
        self.display_order = display_order


def test_d2_empty_inputs_returns_sentinel() -> None:
    assert compute_vision_inputs_hash(None) == VISION_INPUTS_HASH_EMPTY
    assert compute_vision_inputs_hash([]) == VISION_INPUTS_HASH_EMPTY


def test_d2_all_inactive_returns_sentinel() -> None:
    docs = [_FakeDoc("a", "x", is_active=False)]
    assert compute_vision_inputs_hash(docs) == VISION_INPUTS_HASH_EMPTY


def test_d2_stable_for_same_inputs() -> None:
    a = compute_vision_inputs_hash(
        [_FakeDoc("a", "x", name="A", display_order=1), _FakeDoc("b", "y", name="B", display_order=2)]
    )
    b = compute_vision_inputs_hash(
        [_FakeDoc("a", "x", name="A", display_order=1), _FakeDoc("b", "y", name="B", display_order=2)]
    )
    assert a == b
    assert a.startswith("sha256:")


def test_d2_order_independent_by_display_order() -> None:
    forward = compute_vision_inputs_hash(
        [_FakeDoc("a", "x", name="A", display_order=1), _FakeDoc("b", "y", name="B", display_order=2)]
    )
    reversed_ = compute_vision_inputs_hash(
        [_FakeDoc("b", "y", name="B", display_order=2), _FakeDoc("a", "x", name="A", display_order=1)]
    )
    assert forward == reversed_


def test_d2_content_change_flips_hash() -> None:
    before = compute_vision_inputs_hash([_FakeDoc("a", "x", name="A")])
    after = compute_vision_inputs_hash([_FakeDoc("a", "x2", name="A")])
    assert before != after


def test_d2_name_change_flips_hash() -> None:
    before = compute_vision_inputs_hash([_FakeDoc("a", "x", name="A")])
    after = compute_vision_inputs_hash([_FakeDoc("a", "x", name="B")])
    assert before != after


def test_d2_hash_matches_consolidated_helper() -> None:
    derived = compute_vision_inputs_hash([_FakeDoc("a", "x", name="A")])
    raw_hex = derived.removeprefix("sha256:")
    assert vision_inputs_hash_matches_consolidated(derived, raw_hex) is True
    assert vision_inputs_hash_matches_consolidated(derived, "wrong") is False
    assert vision_inputs_hash_matches_consolidated(VISION_INPUTS_HASH_EMPTY, raw_hex) is False
    assert vision_inputs_hash_matches_consolidated(None, raw_hex) is False
    assert vision_inputs_hash_matches_consolidated(derived, None) is False


def test_f1_algorithm_matches_consolidation_service_build_aggregate() -> None:
    from giljo_mcp.services.consolidation_service import ConsolidatedVisionService

    docs = [
        _FakeDoc("doc-b", "Second body.", name="Beta", display_order=2),
        _FakeDoc("doc-a", "First body.", name="Alpha", display_order=1),
        _FakeDoc("doc-c", "Ignored.", name="Gamma", display_order=3, is_active=False),
    ]

    class _StubProductLocal:
        vision_documents = docs

    aggregate_text, source_doc_ids, raw_hex = ConsolidatedVisionService()._build_aggregate(_StubProductLocal())

    derived = compute_vision_inputs_hash(docs)

    assert raw_hex != ""
    assert derived.startswith("sha256:")
    assert derived.removeprefix("sha256:") == raw_hex
    assert vision_inputs_hash_matches_consolidated(derived, raw_hex) is True
    assert source_doc_ids == ["doc-a", "doc-b"]
    assert "# Alpha\n\nFirst body." in aggregate_text
    assert "Gamma" not in aggregate_text




def test_d3_template_renders_all_placeholders() -> None:
    out = render_ctx_bootstrap(
        product_id="pid-1",
        product_name="Acme",
        consolidated_vision_hash="abc123",
        vision_inputs_hash="sha256:zzz",
        new_documents=[{"document_name": "Architecture", "document_type": "architecture"}],
    )
    assert "{{" not in out and "}}" not in out, "All placeholders must be substituted."
    assert "Acme" in out
    assert "pid-1" in out
    assert "abc123" in out
    assert "sha256:zzz" in out
    assert "Architecture (architecture)" in out


def test_d3_template_handles_missing_documents() -> None:
    out = render_ctx_bootstrap(
        product_id="pid-1",
        product_name="Acme",
        consolidated_vision_hash=None,
        vision_inputs_hash=VISION_INPUTS_HASH_EMPTY,
        new_documents=None,
    )
    assert "(none)" in out
    assert "(unset)" in out
    assert "None" not in out


def test_d3_template_constant_exposed() -> None:
    assert "{{product_id}}" in CTX_BOOTSTRAP_TEMPLATE
    assert "{{vision_inputs_hash}}" in CTX_BOOTSTRAP_TEMPLATE




@pytest_asyncio.fixture
async def ctx_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def ctx_product(db_session: AsyncSession, ctx_tenant_key: str) -> Product:
    product = Product(
        id=str(uuid.uuid4()),
        name="BE-5122 Product",
        description="Regression product for CTX feature.",
        tenant_key=ctx_tenant_key,
        is_active=True,
        product_memory={},
        consolidated_vision_hash=None,
    )
    db_session.add(product)
    await db_session.flush()
    return product


@pytest_asyncio.fixture
async def ctx_taxonomy(db_session: AsyncSession, ctx_tenant_key: str) -> TaxonomyType:
    tt = TaxonomyType(
        id=str(uuid.uuid4()),
        tenant_key=ctx_tenant_key,
        abbreviation="CTX",
        label="Context Update",
        color="#9E9E9E",
        sort_order=8,
    )
    db_session.add(tt)
    await db_session.flush()
    return tt


@pytest_asyncio.fixture
async def ctx_vision_doc(db_session: AsyncSession, ctx_tenant_key: str, ctx_product: Product) -> VisionDocument:
    doc = VisionDocument(
        id=str(uuid.uuid4()),
        tenant_key=ctx_tenant_key,
        product_id=ctx_product.id,
        document_name="Architecture",
        document_type="architecture",
        vision_document="Initial inline vision text.",
        storage_type="inline",
    )
    db_session.add(doc)
    await db_session.flush()
    return doc


def _make_project_service(db_session: AsyncSession, tenant_key: str):
    from giljo_mcp.database import tenant_session_context
    from giljo_mcp.services.project_service import ProjectService

    service = ProjectService.__new__(ProjectService)
    service.db_manager = None
    service.tenant_key = tenant_key
    service._websocket_manager = None
    service._logger = __import__("logging").getLogger("test_be_5122")

    import contextlib

    @contextlib.asynccontextmanager
    async def _sess(tk=None):
        with tenant_session_context(db_session, tk or tenant_key):
            yield db_session

    service._get_session = _sess  # type: ignore[assignment]
    return service


@pytest.mark.asyncio
async def test_d4_create_project_ctx_rejects_missing_template_vars(
    db_session: AsyncSession,
    ctx_tenant_key: str,
    ctx_product: Product,
    ctx_taxonomy: TaxonomyType,
) -> None:
    service = _make_project_service(db_session, ctx_tenant_key)

    with pytest.raises(ValidationError) as exc:
        await service.render_ctx_bootstrap_mission(
            product_id=ctx_product.id,
            tenant_key=ctx_tenant_key,
            bootstrap_template_vars=None,
        )
    assert "bootstrap_template_vars" in str(exc.value)


@pytest.mark.asyncio
async def test_d4_create_project_ctx_rejects_non_list_new_documents(
    db_session: AsyncSession,
    ctx_tenant_key: str,
    ctx_product: Product,
    ctx_taxonomy: TaxonomyType,
) -> None:
    service = _make_project_service(db_session, ctx_tenant_key)

    with pytest.raises(ValidationError):
        await service.render_ctx_bootstrap_mission(
            product_id=ctx_product.id,
            tenant_key=ctx_tenant_key,
            bootstrap_template_vars={"new_documents": "not-a-list"},
        )


@pytest.mark.asyncio
async def test_d4_create_project_ctx_renders_mission_from_state(
    db_session: AsyncSession,
    ctx_tenant_key: str,
    ctx_product: Product,
    ctx_taxonomy: TaxonomyType,
    ctx_vision_doc: VisionDocument,
) -> None:
    service = _make_project_service(db_session, ctx_tenant_key)

    rendered = await service.render_ctx_bootstrap_mission(
        product_id=ctx_product.id,
        tenant_key=ctx_tenant_key,
        bootstrap_template_vars={"new_documents": [{"document_name": "Architecture", "document_type": "architecture"}]},
    )
    assert ctx_product.name in rendered
    assert "sha256:" in rendered
    assert "Architecture (architecture)" in rendered




class _StubProduct:
    def __init__(self, hash_hex: str | None, docs: list[_FakeDoc]) -> None:
        self.consolidated_vision_hash = hash_hex
        self.vision_documents = docs


def test_d6_self_close_when_hash_matches() -> None:
    docs = [_FakeDoc("a", "x")]
    derived = compute_vision_inputs_hash(docs)
    raw = derived.removeprefix("sha256:")
    ctx = {
        "project_type_abbreviation": "CTX",
        "product": _StubProduct(raw, docs),
    }
    directive = MissionOrchestrationService._maybe_build_ctx_self_close_directive(ctx)
    assert directive is not None
    assert directive["action"] == "SELF_CLOSE"
    assert directive["status"] == "completed"
    assert directive["vision_inputs_hash"] == derived


def test_d6_no_directive_when_hash_diverges() -> None:
    docs = [_FakeDoc("a", "x")]
    ctx = {
        "project_type_abbreviation": "CTX",
        "product": _StubProduct("deadbeef", docs),
    }
    assert MissionOrchestrationService._maybe_build_ctx_self_close_directive(ctx) is None


def test_d6_no_directive_for_non_ctx_project_type() -> None:
    docs = [_FakeDoc("a", "x")]
    derived = compute_vision_inputs_hash(docs)
    raw = derived.removeprefix("sha256:")
    ctx = {
        "project_type_abbreviation": "BE",
        "product": _StubProduct(raw, docs),
    }
    assert MissionOrchestrationService._maybe_build_ctx_self_close_directive(ctx) is None


def test_d6_no_directive_when_inputs_empty() -> None:
    ctx = {
        "project_type_abbreviation": "CTX",
        "product": _StubProduct(None, []),
    }
    assert MissionOrchestrationService._maybe_build_ctx_self_close_directive(ctx) is None




@pytest_asyncio.fixture
async def ctx_orchestrator_setup(
    db_session: AsyncSession,
    ctx_tenant_key: str,
    ctx_product: Product,
    ctx_taxonomy: TaxonomyType,
    ctx_vision_doc: VisionDocument,
):
    from giljo_mcp.domain.project_status import ProjectStatus
    from giljo_mcp.models import Project
    from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
    from giljo_mcp.services.consolidation_service import ConsolidatedVisionService

    await ConsolidatedVisionService().consolidate_vision_documents(
        product_id=ctx_product.id,
        session=db_session,
        tenant_key=ctx_tenant_key,
        force=False,
    )
    await db_session.refresh(ctx_product)

    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=ctx_tenant_key,
        name="CTX self-close project",
        description="BE-5122 F2 regression",
        mission="CTX self-close mission",
        project_type_id=ctx_taxonomy.id,
        product_id=ctx_product.id,
        status=ProjectStatus.ACTIVE,
        staging_status="staging",
        execution_mode="multi_terminal",
    )
    db_session.add(project)
    await db_session.flush()

    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        job_type="orchestrator",
        tenant_key=ctx_tenant_key,
        project_id=project.id,
        mission="CTX orchestrator mission",
        status="active",
        job_metadata={},
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        agent_id=str(uuid.uuid4()),
        job_id=job_id,
        tenant_key=ctx_tenant_key,
        agent_display_name="orchestrator",
        agent_name="orchestrator",
        status="working",
    )
    db_session.add(execution)
    await db_session.flush()

    return {
        "tenant_key": ctx_tenant_key,
        "product": ctx_product,
        "project": project,
        "job": job,
        "execution": execution,
        "job_id": job_id,
    }


@pytest.mark.asyncio
async def test_f2_server_side_ctx_self_close_transitions_project_to_completed(
    db_session: AsyncSession,
    ctx_orchestrator_setup,
) -> None:
    from sqlalchemy import func, select

    from giljo_mcp.domain.project_status import ProjectStatus
    from giljo_mcp.models.agent_identity import AgentJob

    setup = ctx_orchestrator_setup
    service = MissionOrchestrationService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=db_session,
    )

    response = await service.get_staging_instructions(job_id=setup["job_id"], tenant_key=setup["tenant_key"])

    assert "staging_directive" in response
    directive = response["staging_directive"]
    assert directive["action"] == "STOP"
    assert directive["reason"] == "CTX_SELF_CLOSE"

    await db_session.refresh(setup["project"])
    await db_session.refresh(setup["execution"])
    assert setup["project"].status == ProjectStatus.COMPLETED
    assert setup["project"].completed_at is not None
    assert setup["execution"].status == "complete"
    assert setup["execution"].completed_at is not None

    job_count = await db_session.scalar(
        select(func.count()).select_from(AgentJob).where(AgentJob.project_id == setup["project"].id)
    )
    assert job_count == 1, "Only the orchestrator job should exist; no agents spawned."


@pytest.mark.asyncio
async def test_ctx_self_close_finishes_the_orchestrator_job_like_complete_job(
    db_session: AsyncSession,
    ctx_orchestrator_setup,
) -> None:
    setup = ctx_orchestrator_setup
    service = MissionOrchestrationService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=db_session,
    )

    await service.get_staging_instructions(job_id=setup["job_id"], tenant_key=setup["tenant_key"])

    await db_session.refresh(setup["job"])
    await db_session.refresh(setup["execution"])
    assert setup["job"].status == "completed"
    assert setup["job"].completed_at == setup["execution"].completed_at
    assert setup["execution"].result["summary"]




@pytest.mark.asyncio
async def test_f18_context_update_project_endpoint_returns_open_ctx_project(
    db_session: AsyncSession,
    ctx_tenant_key: str,
    ctx_product: Product,
    ctx_taxonomy: TaxonomyType,
    ctx_vision_doc: VisionDocument,
) -> None:
    from api.endpoints.products.lifecycle import get_context_update_project
    from giljo_mcp.domain.project_status import ProjectStatus
    from giljo_mcp.models import Project
    from giljo_mcp.services.consolidation_service import ConsolidatedVisionService

    await ConsolidatedVisionService().consolidate_vision_documents(
        product_id=ctx_product.id,
        session=db_session,
        tenant_key=ctx_tenant_key,
        force=False,
    )
    await db_session.refresh(ctx_product)

    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=ctx_tenant_key,
        name="CTX endpoint test",
        description="BE-5122 F18 regression",
        mission="CTX endpoint mission",
        project_type_id=ctx_taxonomy.id,
        product_id=ctx_product.id,
        status=ProjectStatus.ACTIVE,
        staging_status="staging",
        execution_mode="multi_terminal",
    )
    db_session.add(project)
    await db_session.flush()

    response = await get_context_update_project(
        product_id=ctx_product.id,
        current_user=None,  # type: ignore[arg-type]
        tenant_key=ctx_tenant_key,
        db=db_session,
    )

    assert response.project_id == str(project.id)
    assert response.product_id == ctx_product.id
    assert response.hash_matches is True
    assert response.consolidated_vision_hash == ctx_product.consolidated_vision_hash


@pytest.mark.asyncio
async def test_f18_context_update_project_endpoint_404_when_no_open_project(
    db_session: AsyncSession,
    ctx_tenant_key: str,
    ctx_product: Product,
    ctx_taxonomy: TaxonomyType,
) -> None:
    from fastapi import HTTPException

    from api.endpoints.products.lifecycle import get_context_update_project

    with pytest.raises(HTTPException) as exc:
        await get_context_update_project(
            product_id=ctx_product.id,
            current_user=None,  # type: ignore[arg-type]
            tenant_key=ctx_tenant_key,
            db=db_session,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_f18_context_update_project_endpoint_tenant_isolation(
    db_session: AsyncSession,
    ctx_tenant_key: str,
    ctx_product: Product,
    ctx_taxonomy: TaxonomyType,
) -> None:
    from fastapi import HTTPException

    from api.endpoints.products.lifecycle import get_context_update_project
    from giljo_mcp.database import tenant_session_context
    from giljo_mcp.domain.project_status import ProjectStatus
    from giljo_mcp.models import Project

    other_tenant = TenantManager.generate_tenant_key()
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=other_tenant,
        name="Foreign tenant CTX",
        description="should not leak",
        mission="foreign tenant mission",
        project_type_id=ctx_taxonomy.id,
        product_id=ctx_product.id,
        status=ProjectStatus.ACTIVE,
        staging_status="staging",
        execution_mode="multi_terminal",
    )
    db_session.add(project)
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        with tenant_session_context(db_session, ctx_tenant_key):
            await get_context_update_project(
                product_id=ctx_product.id,
                current_user=None,  # type: ignore[arg-type]
                tenant_key=ctx_tenant_key,
                db=db_session,
            )
    assert exc.value.status_code == 404
