# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Default Toggle and Depth Configuration for Context Management v4.0

Handover 0840d: Normalized to relational tables and columns.
- Toggles stored in user_field_priorities table (one row per category)
- Depth stored as columns on users table
- product_core and project_description are always on (no toggle rows)

Toggle System:
    7 toggleable categories stored in user_field_priorities table:
    - tech_stack, architecture, testing, vision_documents,
      memory_360, git_history, agent_templates

    2 always-on categories (no rows stored):
    - product_core, project_description

Depth Controls:
    Stored as individual columns on the users table:
    - depth_vision_documents: "medium" (66% summary)
    - depth_memory_last_n: 3 (last 3 projects)
    - depth_git_commits: 25
    - depth_agent_templates: "basic" (~250 tokens)
    - depth_tech_stack_sections: "all"
    - depth_architecture: "overview"
    - execution_mode: "claude_code"

Related:
    - Handover 0840d: User Settings Normalization
    - Handover 0820: Remove Context Priority Framing
    - Handover 0314: Depth Controls Implementation
    - api/endpoints/users.py: Toggle configuration endpoints
    - src/giljo_mcp/models/auth.py: UserFieldPriority model + User depth columns
"""

from typing import Any


# Default toggle states for all categories (including always-on)
# Used for backward-compatible API responses and protocol builder defaults
DEFAULT_FIELD_PRIORITY: dict[str, Any] = {
    "version": "4.0",
    "priorities": {
        "product_core": {"toggle": True},
        "project_description": {"toggle": True},
        "memory_360": {"toggle": True},
        "tech_stack": {"toggle": True},
        "testing": {"toggle": True},
        "vision_documents": {"toggle": True},
        "architecture": {"toggle": True},
        "git_history": {"toggle": False},  # OFF by default until Git Integration enabled
    },
}

# Default toggleable category states (only categories stored in user_field_priorities)
DEFAULT_CATEGORY_TOGGLES: dict[str, bool] = {
    "tech_stack": True,
    "architecture": True,
    "testing": True,
    "vision_documents": True,
    "memory_360": True,
    "git_history": False,  # OFF by default
}

# Default depth values matching users table column defaults
DEFAULT_DEPTH_CONFIG: dict[str, Any] = {
    "vision_documents": "medium",
    "memory_last_n_projects": 3,
    "git_commits": 25,
    "tech_stack_sections": "all",
    "architecture_depth": "overview",
}


DEFAULT_NOTIFICATION_PREFERENCES: dict[str, Any] = {
    "context_tuning_reminder": True,
    "tuning_reminder_threshold": 10,
    # FE-9553, the ruled defaults for the one-notification-model surfaces:
    # lifecycle banners on, advisories in the banner fold on, and popout scope
    # = everything a banner shows. Lifecycle is ~75% of banner volume on a
    # multi-lane night, which is why the scope control exists at all rather
    # than the projection being unconditional.
    "banner_lifecycle_enabled": True,
    "banner_advisories_in_fold": True,
    "popout_scope": "all",
}

# Section keys that map to tuning-eligible product context fields
TUNING_SECTION_TOGGLE_MAP: dict[str, str] = {
    "description": "product_core",
    "tech_stack": "tech_stack",
    "architecture": "architecture",
    "core_features": "architecture",
    "codebase_structure": "architecture",
    "database_type": "tech_stack",
    "backend_framework": "tech_stack",
    "frontend_framework": "tech_stack",
    "quality_standards": "testing",
    "target_platforms": "product_core",
    "vision_documents": "vision_documents",
}
