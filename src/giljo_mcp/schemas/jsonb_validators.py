# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from giljo_mcp.schemas.jsonb_notification_payloads import (  # noqa: F401
    NOTIFICATION_PAYLOAD_VALIDATORS,
    ApiKeyExpiringSoonPayload,
    PendingMigrationsPayload,
    SkillsDriftPayload,
    ToolRenameNoticePayload,
    UpdateAvailablePayload,
    register_notification_payload_validators,
    validate_notification_payload,
)

from giljo_mcp.schemas.jsonb_validators_sequence_runs import (  # noqa: F401
    VALID_REVIEWED_VIA,
    SequenceRunProjectIds,
    SequenceRunProjectStatuses,
    SequenceRunReviewedProjectIds,
    SequenceRunReviewedVia,
    validate_sequence_run_project_ids,
    validate_sequence_run_project_statuses,
    validate_sequence_run_reviewed_project_ids,
    validate_sequence_run_reviewed_via,
)

from giljo_mcp.schemas.jsonb_validators_settings import (  # noqa: F401
    SETTINGS_CATEGORY_VALIDATORS,
    GitIntegrationSettings,
    IntegrationsSettingsData,
    SecuritySettingsData,
    SerenaMcpSettings,
    SettingsData,
    validate_settings_by_category,
)



_JOB_METADATA_CURRENT_STEP_MAX = 2000
_JOB_METADATA_STR_MAX = 200


class AgentJobTodoSteps(BaseModel):
    """Validates the nested job_metadata['todo_steps'] progress cache.

    Written by ProgressService at the report_progress boundary. Step counts are
    server-coerced ints; ``current_step`` is an agent-supplied string and is
    length-capped here (the no-unvalidated-agent-input rule).
    """

    model_config = ConfigDict(extra="allow")

    total_steps: int | None = None
    completed_steps: int | None = None
    skipped_steps: int | None = None
    current_step: str | None = Field(default=None, max_length=_JOB_METADATA_CURRENT_STEP_MAX)


class AgentJobMetadata(BaseModel):
    """Validates agent_jobs.job_metadata JSONB.

    Reflects the ACTUAL key inventory written across the spawn / launch /
    conductor / progress write sites (BE-9000h). ``extra="allow"`` is a
    deliberate, documented extensibility posture: several sites add ad-hoc
    server-built keys (``reused_at``, ``thin_client``, ``context_chunks``,
    demo-seed ``demo`` / ``description``) not worth enumerating. The known
    agent/boundary-supplied strings (``user_id``, ``tool`` and
    ``todo_steps.current_step``) are length-capped; the rest are
    server-constructed.
    """

    model_config = ConfigDict(extra="allow")

    field_toggles: dict | None = None
    depth_config: dict | None = None
    user_id: str | None = Field(default=None, max_length=_JOB_METADATA_STR_MAX)
    tool: str | None = Field(default=None, max_length=_JOB_METADATA_STR_MAX)
    chain_conductor: bool | None = None
    run_id: str | None = None
    created_via: str | None = None
    created_at: str | None = None
    todo_steps: AgentJobTodoSteps | None = None


def validate_agent_job_metadata(data: dict | None) -> dict | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise TypeError("job_metadata must be a dict")
    AgentJobMetadata(**data)
    return data




class GitCommitEntry(BaseModel):
    """Single git commit in product_memory_entries.git_commits.

    ``files_changed`` / ``lines_added`` are optional, normalized to ``0``.
    ``pr_url`` (BE-9256) is freeform and stored verbatim -- never parsed --
    so this shape stays correct for GitHub, Gitea, GitLab, or any other host.
    Length caps (BE-9256 #3) restore the old 64-char sha cap + message/author/pr_url caps -- hard rejection.
    """

    model_config = ConfigDict(extra="ignore")

    sha: str = Field(max_length=64)
    message: str = Field(max_length=500)
    author: str | None = Field(default=None, max_length=200)
    date: str | None = None
    files_changed: int = 0
    lines_added: int = 0
    pr_url: str | None = Field(default=None, max_length=500)

    @field_validator("files_changed", "lines_added", mode="before")
    @classmethod
    def _none_to_zero(cls, v: int | None) -> int:
        if v is None:
            return 0
        return v




class OrganizationSettings(BaseModel):
    """Validates organizations.settings JSONB.

    The settings blob is intentionally schema-less: keys are dynamic per
    organization and the set of recognized keys grows organically. extra="allow"
    is the correct posture here — there is no fixed schema to enforce.
    """

    model_config = ConfigDict(extra="allow")




_EXEC_RESULT_BRANCH_MAX = 255
_EXEC_RESULT_PR_URL_MAX = 2048


class AgentExecutionResult(BaseModel):
    """Validates agent_executions.result JSONB.

    Reflects the structured completion result written by orchestration_service
    when an agent calls complete_job().

    BE-8003j: ``branch`` and ``pr_url`` are the web-coding hand-off fields —
    first-class, documented keys for the isolated-PR delivery model (Claude Code
    web / Codex web deliver an isolated branch/PR rather than writing into a
    shared working tree). ``extra="allow"`` already tolerated them; naming them
    here type-checks + length-caps them and makes the chain hand-off (the
    successor's seed is auto-based on the predecessor's ``branch``) key off a
    documented field, not an ad-hoc extra.
    """

    model_config = ConfigDict(extra="allow")

    summary: str | None = None
    artifacts: list[str] | None = None
    commits: list[str] | None = None
    branch: str | None = Field(default=None, max_length=_EXEC_RESULT_BRANCH_MAX)
    pr_url: str | None = Field(default=None, max_length=_EXEC_RESULT_PR_URL_MAX)


def validate_agent_execution_result(data: dict) -> dict:
    AgentExecutionResult(**data)
    return data




class ProductMemoryConfig(BaseModel):
    """Validates products.product_memory JSONB.

    BE-9261: seed key renamed github -> git_integration. github stays a
    declared field for READ tolerance of pre-rename rows only.
    """

    model_config = ConfigDict(extra="allow")

    git_integration: dict | None = None
    github: dict | None = None
    context: dict | None = None




class ProductTuningState(BaseModel):
    """Validates products.tuning_state JSONB."""

    model_config = ConfigDict(extra="allow")

    last_tuned_at: str | None = None
    last_tuned_at_sequence: int | None = None




class SetupSelectedTools(BaseModel):
    """Validates users.setup_selected_tools JSONB.

    List of AI coding tool names selected during setup wizard.
    Known values: claude_code, codex_cli, opencode, generic; retired tool ids are tolerated.
    """

    items: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("items")
    @classmethod
    def validate_items(cls, v: list[str]) -> list[str]:
        for item in v:
            if len(item) > 200:
                raise ValueError(f"Tool name exceeds 200 characters: {item[:20]}...")
        return v




POPOUT_SCOPE_ALL = "all"
POPOUT_SCOPE_ACTIONABLE = "actionable"
POPOUT_SCOPE_OFF = "off"
POPOUT_SCOPE_CHOICES = (POPOUT_SCOPE_ALL, POPOUT_SCOPE_ACTIONABLE, POPOUT_SCOPE_OFF)


class NotificationPreferences(BaseModel):
    """Validates users.notification_preferences JSONB.

    No extra fields allowed — the schema is fully defined by
    DEFAULT_NOTIFICATION_PREFERENCES.

    FE-9553 added the three notification-model preferences. Every one carries a
    default, so a row written before they existed still validates: that is the
    old-shape answer for this column (tolerance, not a migration). Note that
    the defaults here are what makes a legacy row VALID; what makes it read back
    COMPLETE is the merge in the GET endpoint.
    """

    model_config = ConfigDict(extra="forbid")

    context_tuning_reminder: bool = True
    tuning_reminder_threshold: int = Field(default=10, ge=3, le=1000)

    banner_lifecycle_enabled: bool = True
    banner_advisories_in_fold: bool = True
    popout_scope: Literal["all", "actionable", "off"] = POPOUT_SCOPE_ALL




class APIKeyPermissions(BaseModel):
    """Validates api_keys.permissions JSONB.

    List of permission strings (e.g., ["*"], ["read", "write"]).
    """

    items: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("items")
    @classmethod
    def validate_items(cls, v: list[str]) -> list[str]:
        for item in v:
            if len(item) > 200:
                raise ValueError(f"Permission string exceeds 200 characters: {item[:20]}...")
        return v




class OAuthClientRedirectUris(BaseModel):
    """Validates oauth_clients.redirect_uris JSONB.

    Stored as a JSON array of registered redirect URIs (RFC 7591 §2).
    Schemes are validated by the service layer (HTTPS or http://localhost
    in dev) — this model enforces structural shape and length caps.
    """

    items: list[str] = Field(default_factory=list, max_length=10, min_length=1)

    @field_validator("items")
    @classmethod
    def validate_items(cls, v: list[str]) -> list[str]:
        for uri in v:
            if not isinstance(uri, str):
                raise TypeError(f"redirect_uris items must be strings, got {type(uri).__name__}")
            if not uri:
                raise ValueError("redirect_uris items must be non-empty")
            if len(uri) > 2048:
                raise ValueError(f"redirect_uri exceeds 2048 characters: {uri[:40]}...")
        return v




class ContextIndexKeywords(BaseModel):
    """Validates mcp_context_index.keywords JSONB.

    Array of keyword strings extracted via regex or LLM.
    """

    items: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("items")
    @classmethod
    def validate_items(cls, v: list[str]) -> list[str]:
        for item in v:
            if len(item) > 500:
                raise ValueError(f"Keyword exceeds 500 characters: {item[:20]}...")
        return v




GIT_LOG_TITLED_COMMAND_HINT = "git log --format='%H%x09%s%x09%an' <base>..HEAD"


class GitCommitTitleRequiredError(ValueError):

    def __init__(self, offending: object):
        self.offending = offending
        self.hint = f"Run: {GIT_LOG_TITLED_COMMAND_HINT}"
        super().__init__(
            f"git_commits entry has no commit title: {offending!r}. Provide either a "
            f"{{sha, message, author?, pr_url?}} dict with a non-empty message, or a "
            f"tab-delimited porcelain string '<sha>\\t<subject>\\t<author>' (author "
            f"segment optional). {self.hint}"
        )


def _parse_porcelain_commit_line(line: str) -> dict[str, str]:
    parts = line.split("\t")
    sha = parts[0].strip() if parts else ""
    message = parts[1].strip() if len(parts) > 1 else ""
    author = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
    parsed: dict[str, str] = {"sha": sha, "message": message}
    if author:
        parsed["author"] = author
    return parsed


def validate_git_commits(data: list | None) -> list | None:
    if data is None:
        return None
    normalized: list = []
    for entry in data:
        if isinstance(entry, str):
            raw = entry.rstrip("\r\n")
            if "\t" not in raw:
                raise GitCommitTitleRequiredError(entry)
            parsed = _parse_porcelain_commit_line(raw)
            if not parsed.get("sha") or not parsed.get("message"):
                raise GitCommitTitleRequiredError(entry)
            normalized.append(GitCommitEntry(**parsed).model_dump())
        elif isinstance(entry, dict):
            message = entry.get("message")
            if not isinstance(message, str) or not message.strip():
                raise GitCommitTitleRequiredError(entry)
            normalized.append(GitCommitEntry(**entry).model_dump())
        else:
            raise TypeError(f"git_commits entries must be a dict or SHA/porcelain string, got {type(entry).__name__}")
    return normalized


def validate_product_memory(data: dict | None) -> dict | None:
    if data is None:
        return None
    return ProductMemoryConfig(**data).model_dump(exclude_none=False)


def validate_tuning_state(data: dict | None) -> dict | None:
    if data is None:
        return None
    return ProductTuningState(**data).model_dump(exclude_none=False)


def validate_behavioral_rules(data: list | None) -> list | None:
    if data is None:
        return None
    validated = []
    for item in data:
        if not isinstance(item, str):
            raise TypeError(f"behavioral_rules items must be strings, got {type(item).__name__}")
        validated.append(item)
    return validated


def validate_success_criteria(data: list | None) -> list | None:
    if data is None:
        return None
    validated = []
    for item in data:
        if not isinstance(item, str):
            raise TypeError(f"success_criteria items must be strings, got {type(item).__name__}")
        validated.append(item)
    return validated




class UserApprovalOption(BaseModel):
    """Validates one entry in user_approvals.options."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=100)
    label: str = Field(..., min_length=1, max_length=200)


def validate_user_approval_options(data: list[dict]) -> list[dict]:
    if not isinstance(data, list) or not data:
        raise ValueError("options must be a non-empty list")
    validated = [UserApprovalOption(**opt).model_dump() for opt in data]
    ids = [opt["id"] for opt in validated]
    if len(ids) != len(set(ids)):
        raise ValueError("options must have unique ids")
    return validated


def validate_user_approval_context(data: dict | None) -> dict | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise TypeError("context must be a dict or None")
    import json

    serialized = json.dumps(data)
    if len(serialized) > 16_384:
        raise ValueError("context exceeds 16384 byte soft cap")
    return data




def validate_setup_selected_tools(data: list | None) -> list | None:
    if data is None:
        return None
    return SetupSelectedTools(items=data).items


def validate_notification_preferences(data: dict | None) -> dict | None:
    if data is None:
        return None
    return NotificationPreferences(**data).model_dump()


def validate_api_key_permissions(data: list | None) -> list | None:
    if data is None:
        return None
    return APIKeyPermissions(items=data).items


def validate_context_keywords(data: list | None) -> list | None:
    if data is None:
        return None
    return ContextIndexKeywords(items=data).items


def validate_oauth_client_redirect_uris(data: list) -> list[str]:
    return OAuthClientRedirectUris(items=data).items


def validate_string_list(
    data: list | None,
    field_name: str,
    max_items: int = 1000,
    max_length: int = 5000,
) -> list | None:
    if data is None:
        return None
    if len(data) > max_items:
        raise ValueError(f"{field_name} exceeds maximum of {max_items} items (got {len(data)})")
    validated = []
    for item in data:
        if not isinstance(item, str):
            raise TypeError(f"{field_name} items must be strings, got {type(item).__name__}")
        if len(item) > max_length:
            raise ValueError(f"{field_name} item exceeds {max_length} characters")
        validated.append(item)
    return validated



_VISION_SUMMARY_MAX_CHARS = 500_000


class VisionSummaryEntry(BaseModel):
    """One per-document summary written by update_product_context.

    Validates at the MCP tool boundary BEFORE reaching VisionDocumentRepository.
    doc_id is a UUID string the agent supplies; service-layer enforces tenant
    membership.
    """

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(..., min_length=1, max_length=64)
    light: str = Field(..., max_length=_VISION_SUMMARY_MAX_CHARS)
    medium: str = Field(..., max_length=_VISION_SUMMARY_MAX_CHARS)

    @field_validator("doc_id")
    @classmethod
    def _validate_uuid(cls, v: str) -> str:
        import uuid as _uuid

        try:
            _uuid.UUID(v)
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"doc_id must be a valid UUID: {v[:32]}") from exc
        return v


class ConsolidatedVisionPayload(BaseModel):
    """Product-aggregate consolidated_vision payload from update_product_context."""

    model_config = ConfigDict(extra="forbid")

    light: str = Field(..., max_length=_VISION_SUMMARY_MAX_CHARS)
    medium: str = Field(..., max_length=_VISION_SUMMARY_MAX_CHARS)


def validate_vision_summaries(data: list | None) -> list[dict] | None:
    if data is None:
        return None
    if not isinstance(data, list):
        raise TypeError("vision_summaries must be a list of {doc_id, light, medium} dicts")
    if len(data) > 200:
        raise ValueError(f"vision_summaries exceeds 200-entry cap (got {len(data)})")
    validated = [VisionSummaryEntry(**entry).model_dump() for entry in data]
    doc_ids = [entry["doc_id"] for entry in validated]
    if len(doc_ids) != len(set(doc_ids)):
        raise ValueError("vision_summaries must have unique doc_id values")
    return validated


def validate_consolidated_vision(data: dict | None) -> dict | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise TypeError("consolidated_vision must be a dict with keys {light, medium}")
    return ConsolidatedVisionPayload(**data).model_dump()






class ProviderCancelResponse(BaseModel):
    """Validates the provider subscription-cancel response at the deletion write boundary.

    Captures the relevant subset of the provider cancellation result
    output so the GDPR audit chain can prove the cancel call was
    acknowledged. The payload is persisted into
    ``account_deletion_requests.billing_cancel_response`` (and mirrored into
    ``deletion_receipts.billing_cancel_response``); the column name is
    provider-agnostic so a future pivot does not require another schema
    rename. ``extra="allow"`` so provider payload shape changes (added
    top-level keys) do not break audit writes.
    """

    model_config = ConfigDict(extra="allow")

    subscription_id: str | None = None
    status: str | None = None
    canceled_at: str | None = None
    effective_from: str | None = None
    already_canceled: bool = False


class DeletionReceiptStorageKeyHashes(BaseModel):
    """SHA-256 hex digests of purged backup-bucket keys; raw keys never persisted."""

    items: list[str] = Field(default_factory=list, max_length=1_000_000)

    @field_validator("items")
    @classmethod
    def validate_items(cls, v: list[str]) -> list[str]:
        for item in v:
            if not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}", item):
                raise ValueError(f"invalid SHA-256 hex digest in storage_object_key_sha256s: {item!r}")
        return v
