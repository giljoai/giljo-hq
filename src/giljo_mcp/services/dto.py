# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass
class BroadcastAgentCreatedContext:

    tenant_key: str
    project_id: str
    agent_execution: Any
    agent_id: str
    job_id: str
    agent_display_name: str
    agent_name: str
    mission: str
    phase: int | None
    created_at: datetime
    product_id: str | None = None


@dataclass
class MemoryEntryCreateParams:

    tenant_key: str
    product_id: UUID
    sequence: int
    entry_type: str
    source: str
    timestamp: datetime

    project_id: UUID | None = None
    project_name: str | None = None
    summary: str | None = None
    key_outcomes: list[str] | None = None
    decisions_made: list[str] | None = None
    git_commits: list[dict[str, Any]] | None = None
    deliverables: list[str] | None = None
    metrics: dict[str, Any] | None = None
    priority: int = 3
    significance_score: float = 0.5
    token_estimate: int | None = None
    tags: list[str] | None = field(default=None)
    author_job_id: UUID | None = None
    author_name: str | None = None
    author_type: str | None = None
