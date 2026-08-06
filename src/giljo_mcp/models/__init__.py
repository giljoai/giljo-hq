# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Database models package for Giljo HQ.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️  IMPORT GUIDANCE FOR NEW CODE (Post-Handover 0128a)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ PREFERRED (New Code):
Use specific module imports for clarity and maintainability:

    from giljo_mcp.models.auth import User, APIKey, ApiKeyIpLog, MCPSession
    from giljo_mcp.models.projects import Project, TaxonomyType
    from giljo_mcp.models.agent_identity import AgentJob, AgentExecution
    from giljo_mcp.models.products import Product, VisionDocument
    from giljo_mcp.models.tasks import Task, Message
    from giljo_mcp.models.templates import AgentTemplate
    from giljo_mcp.models.context import MCPContextIndex
    from giljo_mcp.models.config import Configuration, SetupState

⚠️  LEGACY (Existing Code Only):
Backward compatibility maintained for 427 existing imports:

    from giljo_mcp.models import User, Project, AgentJob

This works but obscures which domain the model belongs to.
Use modular imports in new code to benefit from domain organization.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Package Structure (Post-Handover 0128a):
----------------------------------------
src/giljo_mcp/models/
├── base.py            → Base, generate_uuid, generate_project_alias
├── auth.py            → User, APIKey, MCPSession
├── products.py        → Product, VisionDocument, Vision
├── projects.py        → Project, TaxonomyType
├── agent_identity.py  → AgentJob, AgentExecution (Handover 0366a)
├── templates.py       → AgentTemplate, TemplateArchive
├── tasks.py           → Task, Message
├── context.py         → MCPContextIndex
└── config.py          → Configuration, SetupState, DownloadToken, ApiMetrics

Migration Strategy:
-------------------
- New files: Always use modular imports
- Modified files: Update imports while you're editing
- Untouched files: Leave as-is (don't create unnecessary churn)

Benefits of Modular Imports:
-----------------------------
✓ Clear domain boundaries (auth vs projects vs agents)
✓ Easier code navigation
✓ Better IDE autocompletion
✓ Self-documenting dependencies
✓ Reduced merge conflicts

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

# Base classes and utilities
# Agent Identity models (Handover 0366a, 0402)
from .agent_identity import (
    AgentExecution,
    AgentJob,
    AgentTodoItem,
)

# Auth models
from .auth import (
    APIKey,
    ApiKeyIpLog,
    LoginLockout,
    MCPSession,
    User,
    UserFieldPriority,
)
from .base import (
    Base,
    generate_project_alias,
    generate_uuid,
)

# Agent Message Hub models (BE-6054a)
from .comm import (
    CHT_TAXONOMY_ABBR,
    TERMINAL_THREAD_STATUSES,
    VALID_PARTICIPANT_TYPES,
    VALID_THREAD_STATUSES,
    CommParticipant,
    CommThread,
)

# Configuration models
from .config import (
    ApiMetrics,
    Configuration,
    DownloadToken,
    SetupState,
)

# Context models
from .context import (
    MCPContextIndex,
)

# Notification models (IMP-5037a)
from .notifications import (
    VALID_NOTIFICATION_SEVERITIES,
    Notification,
)

# OAuth models
from .oauth import (
    OAuthAuthorizationCode,
    OAuthRefreshToken,
)

# Organization models (Handover 0424a)
from .organizations import (
    Organization,
    OrgMembership,
)

# Product Agent Assignment (junction table for per-product template toggle)
from .product_agent_assignment import (
    ProductAgentAssignment,
)

# Product Memory models (Handover 0390a)
from .product_memory_entry import (
    ProductMemoryEntry,
)

# Product models
from .products import (
    Product,
    ProductArchitecture,
    ProductTechStack,
    ProductTestConfig,
    VisionDocument,
)

# Project models
from .projects import (
    Project,
    TaxonomyType,
)

# Roadmap models (FE-6022a)
from .roadmaps import (
    MAX_ROADMAP_SORT_ORDER,
    VALID_ROADMAP_COMPLEXITIES,
    VALID_ROADMAP_ITEM_TYPES,
    VALID_ROADMAP_RISKS,
    Roadmap,
    RoadmapItem,
)

# Sequence run state machine (BE-6131a — Sequential Multi-Project Runner keystone)
from .sequence_runs import (
    MAX_SEQUENCE_PROJECTS,
    VALID_EXECUTION_MODES,
    VALID_PROJECT_STATUSES,
    VALID_REVIEW_POLICIES,
    VALID_RUN_STATUSES,
    SequenceRun,
)

# Server-level runtime gauges (not tenant-scoped)
from .server_runtime_metrics import ServerRuntimeMetric

# Settings models
from .settings import Settings
from .system_setting import SystemSetting

# Task and message models
from .tasks import (
    Message,
    MessageAcknowledgment,
    MessageCompletion,
    MessageRecipient,
    Task,
)

# Template models
from .templates import (
    AgentTemplate,
    TemplateArchive,
)
from .tenant_skills_ack import TenantSkillsAck

# User approval primitive (BE-5029 Phase A)
from .user_approval import (
    VALID_USER_APPROVAL_STATUSES,
    UserApproval,
)


# Export all for backward compatibility
__all__ = [
    # Agent Message Hub (BE-6054a)
    "CHT_TAXONOMY_ABBR",
    "MAX_ROADMAP_SORT_ORDER",
    # Sequence runner (BE-6131a)
    "MAX_SEQUENCE_PROJECTS",
    "TERMINAL_THREAD_STATUSES",
    "VALID_EXECUTION_MODES",
    "VALID_NOTIFICATION_SEVERITIES",
    "VALID_PARTICIPANT_TYPES",
    "VALID_PROJECT_STATUSES",
    "VALID_REVIEW_POLICIES",
    "VALID_ROADMAP_COMPLEXITIES",
    "VALID_ROADMAP_ITEM_TYPES",
    "VALID_ROADMAP_RISKS",
    "VALID_RUN_STATUSES",
    "VALID_THREAD_STATUSES",
    "VALID_USER_APPROVAL_STATUSES",
    # Auth
    "APIKey",
    "AgentExecution",
    "AgentJob",
    "AgentTemplate",
    "AgentTodoItem",
    "ApiKeyIpLog",
    "ApiMetrics",
    # Base
    "Base",
    "CommParticipant",
    "CommThread",
    # Config
    "Configuration",
    "DownloadToken",
    # Login lockout (SEC-3001a Wave 2 item 6, non-tenant-scoped)
    "LoginLockout",
    # Context
    "MCPContextIndex",
    "MCPSession",
    "Message",
    "MessageAcknowledgment",
    "MessageCompletion",
    "MessageRecipient",
    # Notifications (IMP-5037a)
    "Notification",
    # OAuth
    "OAuthAuthorizationCode",
    "OAuthRefreshToken",
    "OrgMembership",
    # Organizations (Handover 0424a)
    "Organization",
    # Products
    "Product",
    # Product Agent Assignment
    "ProductAgentAssignment",
    "ProductArchitecture",
    # Product Memory (Handover 0390a)
    "ProductMemoryEntry",
    "ProductTechStack",
    "ProductTestConfig",
    # Projects
    "Project",
    # Roadmap (FE-6022a)
    "Roadmap",
    "RoadmapItem",
    "SequenceRun",
    "ServerRuntimeMetric",
    # Settings
    "Settings",
    "SetupState",
    "SystemSetting",
    # Tasks
    "Task",
    "TaxonomyType",
    "TemplateArchive",
    "TenantSkillsAck",
    "User",
    "UserApproval",
    "UserFieldPriority",
    "VisionDocument",
    "generate_project_alias",
    "generate_uuid",
]
