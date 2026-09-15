# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any


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
        "git_history": {"toggle": False},
    },
}

DEFAULT_CATEGORY_TOGGLES: dict[str, bool] = {
    "tech_stack": True,
    "architecture": True,
    "testing": True,
    "vision_documents": True,
    "memory_360": True,
    "git_history": False,
}

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
    "banner_lifecycle_enabled": True,
    "banner_advisories_in_fold": True,
    "popout_scope": "all",
}

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
