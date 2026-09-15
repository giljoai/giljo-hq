# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProductStatistics(BaseModel):
    """Product statistics response.

    Fields match ProductService._get_product_metrics() output plus product metadata.
    """

    product_id: str
    name: str
    is_active: bool
    project_count: int = 0
    unfinished_projects: int = 0
    task_count: int = 0
    unresolved_tasks: int = 0
    vision_documents_count: int = 0
    has_vision: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CascadeImpact(BaseModel):
    """Cascade delete impact analysis.

    Fields match ProductService.get_cascade_impact() output.
    """

    product_id: str
    product_name: str
    total_projects: int = 0
    total_tasks: int = 0
    total_vision_documents: int = 0
    warning: str = ""

    model_config = ConfigDict(from_attributes=True)


class VisionUploadResult(BaseModel):
    """Vision document upload result.

    Fields match ProductVisionService.upload_vision_document() output.
    """

    document_id: str
    document_name: str
    chunks_created: int = 0
    total_tokens: int = 0

    model_config = ConfigDict(from_attributes=True)


class PurgeResult(BaseModel):
    """Purge expired deleted products result."""

    purged_count: int = 0
    purged_ids: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PathValidationResult(BaseModel):
    """Project path validation result."""

    valid: bool
    path: str
    message: str = ""

    model_config = ConfigDict(from_attributes=True)


class GitIntegrationSettings(BaseModel):
    """Git integration settings."""

    enabled: bool = False
    repo_url: str | None = None
    branch: str | None = None
    auto_commit: bool = False

    model_config = ConfigDict(from_attributes=True)
