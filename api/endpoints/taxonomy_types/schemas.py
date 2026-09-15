# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import datetime

from pydantic import BaseModel, Field


class TaxonomyTypeCreate(BaseModel):
    """Request model for creating a taxonomy type."""

    abbreviation: str = Field(
        ...,
        min_length=2,
        max_length=4,
        pattern=r"^[A-Z]+$",
        description="2-4 uppercase letter abbreviation (e.g., BE, FE, API)",
    )
    label: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Human-readable label (e.g., Backend, Frontend)",
    )
    color: str = Field(
        default="#607D8B",
        pattern=r"^#[0-9A-Fa-f]{6}$",
        description="Hex color for UI display",
    )
    sort_order: int = Field(default=0, description="Display ordering in UI dropdowns")


class TaxonomyTypeUpdate(BaseModel):
    """Request model for updating a taxonomy type (partial)."""

    label: str | None = Field(None, min_length=1, max_length=50)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    sort_order: int | None = None


class TaxonomyTypeResponse(BaseModel):
    """Response model for taxonomy type details."""

    id: str
    tenant_key: str
    abbreviation: str
    label: str
    color: str
    sort_order: int
    project_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
