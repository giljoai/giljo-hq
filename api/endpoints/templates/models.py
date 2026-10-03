# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from giljo_mcp.template_validation import validate_harness_name


MAX_TEMPLATE_SIZE = 100 * 1024
MAX_USER_INSTRUCTIONS_SIZE = 50 * 1024


HINT_MAX_LENGTH = 120

NAME_MAX_LENGTH = 100
ROLE_MAX_LENGTH = 50
CLI_TOOL_MAX_LENGTH = 20
BACKGROUND_COLOR_MAX_LENGTH = 7
TOOLS_MAX_LENGTH = 50
CATEGORY_MAX_LENGTH = 50
PRODUCT_ID_MAX_LENGTH = 36


class _TemplateFieldRules(BaseModel):
    """Field checks shared by template create and update requests."""

    @field_validator("user_instructions", check_fields=False)
    @classmethod
    def validate_user_instructions_size(cls, v: str | None) -> str | None:
        if v and len(v.encode("utf-8")) > MAX_USER_INSTRUCTIONS_SIZE:
            raise ValueError("User instructions exceed 50KB limit")
        return v

    @field_validator("model", "effort", check_fields=False)
    @classmethod
    def normalize_hint_fields(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or "inherit"

    @field_validator("cli_tool", mode="before", check_fields=False)
    @classmethod
    def validate_harness(cls, v: str | None) -> str:
        return validate_harness_name(v)


class TemplateCreate(_TemplateFieldRules):
    """Request model for creating a template"""

    product_id: str = Field(..., max_length=PRODUCT_ID_MAX_LENGTH, description="Product this agent belongs to")
    name: str | None = Field(
        None, max_length=NAME_MAX_LENGTH, description="Template name (optional, generated from role when omitted)"
    )
    role: str = Field(..., max_length=ROLE_MAX_LENGTH, description="Agent role")
    cli_tool: str = Field(
        "claude",
        max_length=CLI_TOOL_MAX_LENGTH,
        description="Harness name for this agent (free text, e.g. claude); 'default' = the orchestrator's own",
    )
    custom_suffix: str | None = Field(None, description="Custom suffix for name generation")
    background_color: str | None = Field(
        None, max_length=BACKGROUND_COLOR_MAX_LENGTH, description="Background color (hex)"
    )
    description: str | None = Field(None, description="Template description")
    system_instructions: str | None = Field(
        None, description="Ignored on create; backend always injects canonical MCP bootstrap"
    )
    user_instructions: str | None = Field(None, description="User-customizable role identity prose (max 50KB)")
    model: str | None = Field(
        "inherit",
        max_length=HINT_MAX_LENGTH,
        description="Preferred model, free text for the harness; 'inherit' = same as the orchestrator",
    )
    effort: str | None = Field(
        "inherit",
        max_length=HINT_MAX_LENGTH,
        description="Preferred effort level, free text for the harness; 'inherit' = same as the orchestrator",
    )
    tools: str | None = Field(None, max_length=TOOLS_MAX_LENGTH, description="Tool selection (null = inherit all)")
    behavioral_rules: list[str] | None = Field(default_factory=list)
    success_criteria: list[str] | None = Field(default_factory=list)
    tags: list[str] | None = Field(default_factory=list)
    is_default: bool = Field(default=False, description="Set as default for this role")
    is_active: bool = Field(default=False, description="Deprecated, inert: the per-product switch is the control")
    category: str | None = Field(None, max_length=CATEGORY_MAX_LENGTH, description="Template category (deprecated)")


class TemplateUpdate(_TemplateFieldRules):
    """Request model for updating a template"""

    system_instructions: str | None = Field(
        None, description="System instructions are read-only via API; presence triggers a 403"
    )
    user_instructions: str | None = Field(None, description="User-customizable instructions (max 50KB)")
    name: str | None = Field(None, max_length=NAME_MAX_LENGTH)
    role: str | None = Field(None, max_length=ROLE_MAX_LENGTH)
    cli_tool: str | None = Field(None, max_length=CLI_TOOL_MAX_LENGTH)
    background_color: str | None = Field(None, max_length=BACKGROUND_COLOR_MAX_LENGTH)
    description: str | None = None
    model: str | None = Field(None, max_length=HINT_MAX_LENGTH)
    effort: str | None = Field(None, max_length=HINT_MAX_LENGTH)
    behavioral_rules: list[str] | None = None
    success_criteria: list[str] | None = None
    tags: list[str] | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class TemplateResponse(BaseModel):
    """Response model for template operations"""

    id: str
    tenant_key: str
    product_id: str | None
    name: str
    role: str
    cli_tool: str
    background_color: str | None
    description: str | None
    system_instructions: str = Field(..., description="Read-only MCP coordination instructions")
    user_instructions: str | None = Field(None, description="User-customizable instructions")
    model: str | None
    effort: str | None = Field(
        None, description="Preferred effort level (free text; 'inherit' = same as the orchestrator)"
    )
    tools: str | None
    behavioral_rules: list[str]
    success_criteria: list[str]
    tags: list[str]
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime | None
    category: str | None = None
    variables: list[str] = []
    version: str = "1.0.0"
    avg_generation_ms: float | None = None
    created_by: str | None = None
    is_system_role: bool = Field(default=False, description="True when template is system managed")
    can_reset: bool = Field(default=False, description="True when a factory default exists to reset this agent to")


class TemplateHistoryResponse(BaseModel):
    """Response model for template history"""

    id: str
    template_id: str
    name: str
    version: str
    system_instructions: str | None = None
    user_instructions: str | None = None
    archive_reason: str | None
    archive_type: str
    archived_by: str | None
    archived_at: datetime
    is_restorable: bool
    usage_count_at_archive: int | None
    avg_generation_ms_at_archive: float | None


class TemplateResetFailure(BaseModel):
    """One agent a bulk reset could not complete, and why."""

    name: str
    error: str


class TemplateResetAllResponse(BaseModel):
    """Per-agent outcome of resetting every factory-born agent of one product.

    Three lists rather than a count, because a partial run is a real outcome the
    user has to be told about by name: which agents went back to their default,
    which were left alone because they have no default to return to, and which
    failed.
    """

    reset: list[str] = Field(default_factory=list, description="Agents restored to their shipped default")
    skipped: list[str] = Field(default_factory=list, description="Agents with no factory default to return to")
    failed: list[TemplateResetFailure] = Field(default_factory=list, description="Agents that could not be reset")


class TemplatePreviewRequest(BaseModel):
    """Request model for template preview"""

    variables: dict[str, str] = Field(default_factory=dict, description="Variable substitutions")
    augmentations: str | None = Field(None, description="Additional augmentation content")


class TemplatePreviewResponse(BaseModel):
    """Response model for template preview"""

    template_id: str
    cli_tool: str = Field(..., description="CLI tool type")
    preview: str = Field(..., description="Rendered template content")
    variables_used: list[str] = Field(default_factory=list, description="Variables found in template")
