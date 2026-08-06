# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Context fetching tools for thin client orchestration.

This module provides MCP tools for on-demand context fetching with user-configured depth levels.
These tools support the thin client architecture (Handover 0315) by allowing orchestrators to
fetch only the context they need, reducing token usage from ~3500 to ~600 tokens.

PUBLIC Tool (Handover 0350a - exposed via MCP):
- fetch_context: Unified context dispatcher (saves ~720 tokens vs 9 individual tools)

INTERNAL Tools (10 total - called by fetch_context, NOT exposed via MCP):
- get_vision_document: Fetch vision document chunks with configurable chunking depth
- get_360_memory: Fetch sequential project history from product memory
- get_git_history: Fetch git commit history (when git integration enabled)
- get_agent_templates: Fetch agent template metadata
- get_tech_stack: Fetch tech stack information (Handover 0316: Fixed to use config_data)
- get_architecture: Fetch architecture documentation (Handover 0316: Fixed to use config_data)
- get_product_context: Fetch product metadata and core features (Handover 0316: NEW)
- get_project: Fetch project metadata and mission (Handover 0316: NEW)
- get_testing: Fetch testing configuration and quality standards (Handover 0316: NEW)
- get_self_identity: Fetch agent's own template for self-identity context (Handover 0430: NEW)
"""

from .fetch_context import fetch_context  # Handover 0350a: PUBLIC - unified dispatcher
from .get_360_memory import get_360_memory
from .get_agent_templates import get_agent_templates
from .get_architecture import get_architecture
from .get_git_history import get_git_history
from .get_product_context import get_product_context  # Handover 0316: NEW
from .get_project import get_project  # Handover 0316: NEW
from .get_self_identity import get_self_identity  # Handover 0430: NEW
from .get_tech_stack import get_tech_stack
from .get_testing import get_testing  # Handover 0316: NEW
from .get_vision_document import get_vision_document


__all__ = [
    "fetch_context",  # Handover 0350a: PUBLIC - exposed via MCP HTTP
    "get_360_memory",
    "get_agent_templates",
    "get_architecture",
    "get_git_history",
    "get_product_context",  # Handover 0316: NEW
    "get_project",  # Handover 0316: NEW
    "get_self_identity",  # Handover 0430: NEW
    "get_tech_stack",
    "get_testing",  # Handover 0316: NEW
    "get_vision_document",
]
