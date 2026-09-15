# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from pydantic import BaseModel, ConfigDict, Field


class TaskListResponse(BaseModel):
    """Task list with count."""

    tasks: list[dict] = Field(default_factory=list)
    count: int = 0

    model_config = ConfigDict(from_attributes=True)


class TaskUpdateResult(BaseModel):
    """Task update result."""

    task_id: str
    updated_fields: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TaskSummary(BaseModel):
    """Task summary statistics."""

    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_priority: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class ConversionResult(BaseModel):
    """Task-to-project conversion result."""

    task_id: str
    project_id: str
    project_name: str
    project_taxonomy_alias: str | None = None
    product_id: str | None = None
    product_name: str | None = None

    model_config = ConfigDict(from_attributes=True)
