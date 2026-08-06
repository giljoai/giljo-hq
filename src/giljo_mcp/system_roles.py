# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
System-managed agent role declarations.

Roles listed here are protected by the platform - the Template Manager UI and
template APIs should treat them as immutable, always-on components that cannot
be toggled, exported, or modified by end users.
"""

from __future__ import annotations


SYSTEM_MANAGED_ROLES: set[str] = {"orchestrator"}

# BE-9333: the ONE agent_name that legitimately resolves to no template row.
# ``template_seeder`` skips the system-managed roles above, so no ``orchestrator``
# row is ever created, and the documented chain sub-orchestrator spawn
# (``spawn_job(agent_display_name="orchestrator", agent_name="orchestrator")``)
# binds no template BY DESIGN — its identity is composed at read time instead.
# Every OTHER unresolvable name is a caller mistake, and the spawn allowlist
# rejects it rather than silently substituting the default orchestrator.
ORCHESTRATOR_AGENT_NAME: str = "orchestrator"
