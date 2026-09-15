# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from pydantic import BaseModel, ConfigDict


class TemplateDetail(BaseModel):
    """Single template detail for get_template response."""

    id: str
    name: str
    role: str | None = None
    content: str | None = None
    cli_tool: str | None = None
    background_color: str | None = None
    category: str | None = None
    tenant_key: str | None = None
    product_id: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TemplateGetResult(BaseModel):
    """Single template retrieval result."""

    template: TemplateDetail

    model_config = ConfigDict(from_attributes=True)
