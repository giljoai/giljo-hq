# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Service-layer Pydantic response models for Giljo HQ.

Re-exports all domain-specific response models so that existing imports
(``from giljo_mcp.schemas.service_responses import X``) continue to work
unchanged. New code may import directly from domain sub-modules.

Split from monolithic service_responses.py in Sprint 002e.
"""

from giljo_mcp.schemas.responses.auth import (
    ApiKeyCreateResult,
    ApiKeyInfo,
    AuthResult,
    CredentialStatusResult,
    SetupState,
    SetupStateInfo,
    UserInfo,
)
from giljo_mcp.schemas.responses.consolidation import (
    ConsolidationResult,
    MultiLevelSummaryLevel,
    SummarizeMultiLevelResult,
    SummarizeSingleResult,
    SummaryLevel,
)
from giljo_mcp.schemas.responses.orchestration import (
    AgentStatusChangeEvent,
    AgentTodoCounts,
    AgentWorkflowDetail,
    CompleteJobResult,
    DismissResult,
    ErrorReportResult,
    InstructionsResponse,
    JobListResult,
    MissionResponse,
    MissionUpdateResult,
    PendingJobsResult,
    ProgressResult,
    ReactivationResult,
    SpawnResult,
    StagingDirective,
    SuccessionContextResult,
    SuccessionResult,
    SuccessionStatus,
    ThreadUnreadDetail,
    WorkflowStatus,
    build_next_action,
)
from giljo_mcp.schemas.responses.product import (
    CascadeImpact,
    GitIntegrationSettings,
    PathValidationResult,
    ProductStatistics,
    PurgeResult,
    VisionUploadResult,
)
from giljo_mcp.schemas.responses.project import (
    ActiveProjectDetail,
    CanCloseResult,
    CloseoutData,
    CloseoutPromptResult,
    NuclearDeleteResult,
    ProjectCloseOutResult,
    ProjectCompleteResult,
    ProjectData,
    ProjectDetail,
    ProjectLaunchResult,
    ProjectListItem,
    ProjectMissionUpdateResult,
    ProjectPurgeResult,
    ProjectResumeResult,
    ProjectSummaryResult,
    ProjectSwitchResult,
    ProjectTypeInfo,
    SoftDeleteResult,
)
from giljo_mcp.schemas.responses.shared import (
    DeleteResult,
    OperationResult,
    PaginatedResult,
)
from giljo_mcp.schemas.responses.task import (
    ConversionResult,
    TaskListResponse,
    TaskSummary,
    TaskUpdateResult,
)
from giljo_mcp.schemas.responses.template import (
    TemplateDetail,
    TemplateGetResult,
)


__all__ = [
    "ActiveProjectDetail",
    # Orchestration
    "AgentStatusChangeEvent",
    "AgentTodoCounts",
    "AgentWorkflowDetail",
    "ApiKeyCreateResult",
    "ApiKeyInfo",
    # Auth
    "AuthResult",
    "CanCloseResult",
    "CascadeImpact",
    "CloseoutData",
    "CloseoutPromptResult",
    "CompleteJobResult",
    "ConsolidationResult",
    "ConversionResult",
    "CredentialStatusResult",
    # Shared
    "DeleteResult",
    "DismissResult",
    "ErrorReportResult",
    "GitIntegrationSettings",
    "InstructionsResponse",
    "JobListResult",
    "MissionResponse",
    "MissionUpdateResult",
    "MultiLevelSummaryLevel",
    "NuclearDeleteResult",
    "OperationResult",
    "PaginatedResult",
    "PathValidationResult",
    "PendingJobsResult",
    # Product
    "ProductStatistics",
    "ProgressResult",
    "ProjectCloseOutResult",
    "ProjectCompleteResult",
    "ProjectData",
    "ProjectDetail",
    "ProjectLaunchResult",
    "ProjectListItem",
    "ProjectMissionUpdateResult",
    "ProjectPurgeResult",
    "ProjectResumeResult",
    "ProjectSummaryResult",
    "ProjectSwitchResult",
    # Project
    "ProjectTypeInfo",
    "PurgeResult",
    "ReactivationResult",
    "SetupState",
    "SetupStateInfo",
    "SoftDeleteResult",
    "SpawnResult",
    "StagingDirective",
    "SuccessionContextResult",
    "SuccessionResult",
    "SuccessionStatus",
    "SummarizeMultiLevelResult",
    "SummarizeSingleResult",
    # Consolidation
    "SummaryLevel",
    # Task
    "TaskListResponse",
    "TaskSummary",
    "TaskUpdateResult",
    # Template
    "TemplateDetail",
    "TemplateGetResult",
    "ThreadUnreadDetail",
    "UserInfo",
    "VisionUploadResult",
    "WorkflowStatus",
    # BE-8003a next_action envelope
    "build_next_action",
]
