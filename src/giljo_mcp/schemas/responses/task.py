# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Task service response models."""

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
    # BE-9382: the promoted project's rendered serial (e.g. "0017" -- conversion
    # strips the type, so there is no abbreviation prefix). Read off the DB's own
    # ``Project.taxonomy_alias`` column_property so the alias the agent gets is
    # the one the dashboard shows, with no second rendering rule. Optional
    # because a caller that never reads it (the REST convert endpoint) is
    # unaffected.
    project_taxonomy_alias: str | None = None
    # BE-9415: name the landing, not just the project. The conversion binds to
    # the TASK's product rather than the ambient active one, and echoing both id
    # and name lets a caller self-check where the promotion went for the cost of
    # one field read -- the same contract BE-9411 gave the create tools. Optional
    # so the REST convert endpoint, which never reads them, is unaffected.
    product_id: str | None = None
    product_name: str | None = None

    model_config = ConfigDict(from_attributes=True)
