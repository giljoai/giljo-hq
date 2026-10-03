# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import ColumnProperty, class_mapper

from api.endpoints.agent_jobs.models import AgentExecutionResponse, JobResponse
from api.endpoints.products.models import ProductResponse
from api.endpoints.projects.models import ProjectResponse
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.schemas.responses.project import (
    ActiveProjectDetail,
    ProjectBase,
    ProjectData,
    ProjectDetail,
)




def _model_attribute_names(model_cls: type) -> set[str]:
    names: set[str] = set()
    mapper = class_mapper(model_cls)
    for prop in mapper.iterate_properties:
        if isinstance(prop, ColumnProperty):
            names.add(prop.key)
    return names


def _schema_field_names(schema_cls: type[BaseModel]) -> set[str]:
    return set(schema_cls.model_fields.keys())


def _assert_parity(
    model_cls: type,
    schema_cls: type[BaseModel],
    allowlist: dict[str, str],
    model_label: str,
    schema_label: str,
) -> None:
    model_cols = _model_attribute_names(model_cls)
    schema_fields = _schema_field_names(schema_cls)
    missing = model_cols - schema_fields - set(allowlist.keys())
    assert not missing, (
        f"\nSchema-parity failure for {model_label} → {schema_label}:\n"
        f"  Model column(s) missing from both schema AND allowlist: {sorted(missing)}\n"
        f"\n"
        f"Fix one of:\n"
        f"  (a) Add the field to {schema_label} (with appropriate construction-site updates), OR\n"
        f"  (b) Add an entry to the allowlist in tests/schemas/test_response_parity_all_models.py\n"
        f"      with a one-line documented reason explaining why this column should NOT\n"
        f"      be exposed via {schema_label}.\n"
        f"\n"
        f"The CE-0036 bug class (silent drift between REST + MCP schemas representing\n"
        f"the same entity) is what this test prevents. Treat allowlist additions as\n"
        f"deliberate decisions, not friction.\n"
    )



PROJECT_REST_ALLOWLIST: dict[str, str] = {
    "tenant_key": "Multi-tenant isolation — never exposed via REST (server-side filter)",
    "deleted_at": "Soft-delete timestamp surfaced via ProjectListResponse's /deleted listing, not main project shape",
    "cancellation_reason": (
        "Exposed via MCP ProjectDetail but not REST ProjectResponse. CE-0038 "
        "consolidation should decide whether to surface in the consolidated base."
    ),
    "early_termination": (
        "Exposed via MCP ProjectDetail but not REST ProjectResponse. CE-0038 "
        "consolidation should decide whether to surface in the consolidated base."
    ),
    "orchestrator_summary": "Internal closeout workflow state, not user-facing on project shape",
    "closeout_prompt": "Internal closeout workflow state, not user-facing on project shape",
    "closeout_executed_at": "Internal closeout workflow state, not user-facing on project shape",
    "closeout_checklist": "Internal closeout workflow state, not user-facing on project shape",
    "ever_launched_at": (
        "BE-9085b internal durable 'was ever launched' signal — powers the pre-launch-"
        "workproduct detector's restage false-positive suppression; not exposed via API"
    ),
}

PROJECT_MCP_DETAIL_ALLOWLIST: dict[str, str] = {
    "deleted_at": "Soft-delete timestamp; full-detail shape is for active projects",
    "orchestrator_summary": "Internal closeout workflow state",
    "closeout_prompt": "Internal closeout workflow state",
    "closeout_executed_at": "Internal closeout workflow state",
    "closeout_checklist": "Internal closeout workflow state",
    "ever_launched_at": "BE-9085b internal durable launch signal — detector-only, not exposed via API",
}

PROJECT_MCP_DATA_ALLOWLIST: dict[str, str] = {
    "alias": "Compact update/cancel response — alias not relevant to caller",
    "staging_status": "Compact update/cancel response — caller already knows staging context",
    "implementation_launched_at": (
        "Compact update/cancel response — implementation gate is read from "
        "ProjectDetail or REST ProjectResponse, not from compact update results"
    ),
    "tenant_key": "Multi-tenant isolation",
    "reviewed_at": "Human-review stamp: REST-only, read by the Jobs board via /active",
    "deleted_at": "Soft-delete timestamp not relevant to compact shape",
    "ever_launched_at": "BE-9085b internal durable launch signal — detector-only, not exposed via API",
    "orchestrator_summary": "Internal closeout workflow state",
    "closeout_prompt": "Internal closeout workflow state",
    "closeout_executed_at": "Internal closeout workflow state",
    "closeout_checklist": "Internal closeout workflow state",
}


def test_project_rest_response_parity():
    _assert_parity(
        Project,
        ProjectResponse,
        PROJECT_REST_ALLOWLIST,
        model_label="Project",
        schema_label="REST ProjectResponse (api/endpoints/projects/models.py)",
    )


def test_project_mcp_detail_parity():
    _assert_parity(
        Project,
        ProjectDetail,
        PROJECT_MCP_DETAIL_ALLOWLIST,
        model_label="Project",
        schema_label="MCP ProjectDetail (src/giljo_mcp/schemas/responses/project.py)",
    )


def test_project_mcp_data_parity():
    _assert_parity(
        Project,
        ProjectData,
        PROJECT_MCP_DATA_ALLOWLIST,
        model_label="Project",
        schema_label="MCP ProjectData (src/giljo_mcp/schemas/responses/project.py)",
    )



PRODUCT_REST_ALLOWLIST: dict[str, str] = {
    "tenant_key": "Multi-tenant isolation — never exposed via REST",
    "org_id": "Organization FK is SaaS-only context; CE single-org never needs it surfaced",
    "deleted_at": "Soft-delete timestamp surfaced via DeletedProductResponse, not main product shape",
    "quality_standards": (
        "Lives on ProductTestConfig (1:1) and is surfaced via the test_config nested "
        "object on ProductResponse; this column on Product itself is legacy/redundant"
    ),
    "tuning_state": "Internal Product Context Tuning state — not user-facing",
    "consolidated_vision_light": "Internal consolidated-summary cache; surfaced via vision endpoints",
    "consolidated_vision_light_tokens": "Internal consolidated-summary cache; surfaced via vision endpoints",
    "consolidated_vision_medium": "Internal consolidated-summary cache; surfaced via vision endpoints",
    "consolidated_vision_medium_tokens": "Internal consolidated-summary cache; surfaced via vision endpoints",
    "consolidated_vision_hash": "Internal consolidated-summary cache; surfaced via vision endpoints",
    "consolidated_at": "Internal consolidated-summary cache timestamp",
}


def test_product_rest_response_parity():
    _assert_parity(
        Product,
        ProductResponse,
        PRODUCT_REST_ALLOWLIST,
        model_label="Product",
        schema_label="REST ProductResponse (api/endpoints/products/models.py)",
    )



AGENT_JOB_REST_ALLOWLIST: dict[str, str] = {
    "template_id": ("Template FK is internal provenance — frontend renders agent_display_name, not template lineage"),
    "job_metadata": (
        "Job-level configuration JSONB; surfaced via the spawn_agent flow on the "
        "way IN, not echoed back on the JobResponse on the way OUT"
    ),
    "job_type": (
        "Mapped onto JobResponse.agent_display_name at the service layer "
        "(see ProjectService.get_project agent_dicts). The job_type column is the "
        "canonical agent-type label; UI consumes it under the display-name field."
    ),
}


def test_agent_job_rest_response_parity():
    _assert_parity(
        AgentJob,
        JobResponse,
        AGENT_JOB_REST_ALLOWLIST,
        model_label="AgentJob",
        schema_label="REST JobResponse (api/endpoints/agent_jobs/models.py)",
    )



AGENT_EXECUTION_REST_ALLOWLIST: dict[str, str] = {
    "id": (
        "AgentExecutionResponse exposes agent_id (succession-stable identity) instead of "
        "the internal execution row UUID. The internal id is a DB-integrity primary key, "
        "not part of the public contract."
    ),
    "tenant_key": "Multi-tenant isolation — never exposed via REST",
    "agent_display_name": "Compact response — display name lives on JobResponse, not the execution projection",
    "agent_name": "Compact response — name lives on JobResponse, not the execution projection",
    "started_at": "Compact response — timing detail lives on JobResponse",
    "completed_at": "Compact response — timing detail lives on JobResponse",
    "current_task": "Compact response — running task detail lives on JobResponse",
    "block_reason": "Compact response — block detail lives on JobResponse",
    "health_status": "Health-check internals not part of execution public contract",
    "last_health_check": "Health-check internals not part of execution public contract",
    "health_failure_count": "Health-check internals not part of execution public contract",
    "last_progress_at": "Progress-timing internal — not part of the execution public contract (the health route that surfaced it was retired in BE-9143)",
    "last_message_check_at": "Internal message-queue tracking",
    "mission_acknowledged_at": "Internal mission-acknowledgement tracking",
    "last_activity_at": "Internal heartbeat tracking",
    "tool_type": "Surfaced via JobResponse.tool_type, not compact execution projection",
    "messages_sent_count": "Surfaced via JobResponse counters, not compact execution projection",
    "messages_waiting_count": "Surfaced via JobResponse counters, not compact execution projection",
    "messages_read_count": "Surfaced via JobResponse counters, not compact execution projection",
    "result": "Surfaced via JobResponse.result, not compact execution projection",
    "accumulated_duration_seconds": "Surfaced via JobResponse, not compact execution projection",
    "working_started_at": "Internal timer anchor (BE-5107) — duration_seconds property exposed instead",
    "reactivation_count": "Surfaced via JobResponse, not compact execution projection",
    "project_phase": (
        "Surfaced via MissionResponse.project_phase to orchestrators; not part of the compact AgentExecutionResponse"
    ),
}


def test_agent_execution_rest_response_parity():
    _assert_parity(
        AgentExecution,
        AgentExecutionResponse,
        AGENT_EXECUTION_REST_ALLOWLIST,
        model_label="AgentExecution",
        schema_label="REST AgentExecutionResponse (api/endpoints/agent_jobs/models.py)",
    )



ALLOWLIST_FIXTURES: list[tuple[str, type, dict[str, Any]]] = [
    ("Project / REST ProjectResponse", Project, PROJECT_REST_ALLOWLIST),
    ("Project / MCP ProjectDetail", Project, PROJECT_MCP_DETAIL_ALLOWLIST),
    ("Project / MCP ProjectData", Project, PROJECT_MCP_DATA_ALLOWLIST),
    ("Product / REST ProductResponse", Product, PRODUCT_REST_ALLOWLIST),
    ("AgentJob / REST JobResponse", AgentJob, AGENT_JOB_REST_ALLOWLIST),
    ("AgentExecution / REST AgentExecutionResponse", AgentExecution, AGENT_EXECUTION_REST_ALLOWLIST),
]


@pytest.mark.parametrize("label,model_cls,allowlist", ALLOWLIST_FIXTURES)
def test_allowlist_entries_reference_real_columns(
    label: str,
    model_cls: type,
    allowlist: dict[str, str],
) -> None:
    model_cols = _model_attribute_names(model_cls)
    stale = set(allowlist.keys()) - model_cols
    assert not stale, (
        f"\nStale allowlist entries for {label}:\n"
        f"  Entries that don't match any column on {model_cls.__name__}: {sorted(stale)}\n"
        f"\n"
        f"Either the column was renamed/dropped (update the allowlist) or the\n"
        f"entry was added by mistake. Stale allowlist entries can mask real gaps,\n"
        f"so they must be kept in sync with the model.\n"
    )




def test_project_response_inherits_project_base() -> None:
    assert issubclass(ProjectResponse, ProjectBase), (
        "REST ProjectResponse must inherit ProjectBase (CE-0038 consolidation). Check api/endpoints/projects/models.py."
    )


def test_project_detail_inherits_project_base() -> None:
    assert issubclass(ProjectDetail, ProjectBase), (
        "MCP ProjectDetail must inherit ProjectBase (CE-0038 consolidation). "
        "Check src/giljo_mcp/schemas/responses/project.py."
    )


def test_project_data_inherits_project_base() -> None:
    assert issubclass(ProjectData, ProjectBase), (
        "MCP ProjectData must inherit ProjectBase (CE-0038 consolidation). "
        "Check src/giljo_mcp/schemas/responses/project.py."
    )


def test_active_project_detail_inherits_project_base() -> None:
    assert issubclass(ActiveProjectDetail, ProjectBase), (
        "ActiveProjectDetail must inherit ProjectBase (CE-0038 consolidation). "
        "Check src/giljo_mcp/schemas/responses/project.py."
    )


def test_project_base_fields_are_intersection_of_subclasses() -> None:
    base_fields = set(ProjectBase.model_fields.keys())
    rest_fields = set(ProjectResponse.model_fields.keys())
    detail_fields = set(ProjectDetail.model_fields.keys())
    data_fields = set(ProjectData.model_fields.keys())

    missing_in_rest = base_fields - rest_fields
    missing_in_detail = base_fields - detail_fields
    missing_in_data = base_fields - data_fields

    assert not (missing_in_rest or missing_in_detail or missing_in_data), (
        "ProjectBase fields must appear on every Project subclass.\n"
        f"  Missing from REST ProjectResponse: {sorted(missing_in_rest)}\n"
        f"  Missing from MCP ProjectDetail:    {sorted(missing_in_detail)}\n"
        f"  Missing from MCP ProjectData:      {sorted(missing_in_data)}\n"
        "\n"
        "If a field doesn't belong on every shape, move it out of ProjectBase\n"
        "and into the specific subclasses that need it."
    )
