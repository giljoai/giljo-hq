# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Pydantic validation models for remaining JSONB columns.

These models enforce schema consistency at write time for JSONB columns
that intentionally remain as flexible storage.

Created: Handover 0840f
Updated: Handover 0962c — added AgentExecutionResult, template
    validators; fixed ProductMemoryConfig field names; removed stale todo_steps from
    AgentJobMetadata.
Updated: Sprint 002d — removed 6 dead validators + CloseoutChecklistItem.
Updated: BE-8000j — removed 4 dead validator models (AgentTemplateMetadata,
    MemoryEntryMetrics, SetupValidationEntry, MCPSessionData) + validate_job_metadata;
    their JSONB columns are never populated in current code, so they validated nothing.
Updated: BE-9000h — rewrote AgentJobMetadata to the ACTUAL job_metadata key
    inventory (field_toggles/depth_config/user_id/tool/chain_conductor/run_id/
    created_via/created_at/todo_steps) + added validate_agent_job_metadata, now
    called at every job_metadata write boundary; length-caps the agent-supplied
    strings (user_id, tool, todo_steps.current_step).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Notification.payload & system-banner payload schemas were extracted to a
# sibling module (INF-6132) to keep this file under the 800-line guardrail.
# Re-exported here so existing imports keep working unchanged.
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

# Settings.settings_data category-specific schemas were extracted to a
# sibling module (BE-9040 cleanup) to keep this file under the 800-line
# guardrail. Re-exported here so existing imports keep working unchanged.
from giljo_mcp.schemas.jsonb_validators_settings import (  # noqa: F401
    SETTINGS_CATEGORY_VALIDATORS,
    GitIntegrationSettings,
    IntegrationsSettingsData,
    SecuritySettingsData,
    SerenaMcpSettings,
    SettingsData,
    validate_settings_by_category,
)


# --- AgentJob.job_metadata ---

# Cap agent/boundary-supplied strings so a runaway or malicious agent cannot
# store an unbounded blob in the job_metadata JSONB (no-unvalidated-agent-input
# rule). Generous headroom over any legitimate value.
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
    """Validate agent_jobs.job_metadata at every write boundary (BE-9000h).

    Type-checks the known orchestration keys and length-caps the
    agent/boundary-supplied strings (``user_id``, ``tool`` and
    ``todo_steps.current_step``). ``extra="allow"`` means ad-hoc server-built
    keys pass through untouched; the ORIGINAL payload is returned unchanged on
    success (no reshaping, no null-padding of absent keys). Raises
    ``pydantic.ValidationError`` when a known field is the wrong type or an
    agent-supplied string exceeds its cap, which the service boundary surfaces
    as a clean rejection rather than letting a malformed blob reach the column.
    """
    if data is None:
        return None
    if not isinstance(data, dict):
        raise TypeError("job_metadata must be a dict")
    AgentJobMetadata(**data)
    return data


# --- ProductMemoryEntry arrays ---


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
        """Normalize missing/None optional integer counts to 0."""
        if v is None:
            return 0
        return v


# --- Organization.settings ---


class OrganizationSettings(BaseModel):
    """Validates organizations.settings JSONB.

    The settings blob is intentionally schema-less: keys are dynamic per
    organization and the set of recognized keys grows organically. extra="allow"
    is the correct posture here — there is no fixed schema to enforce.
    """

    model_config = ConfigDict(extra="allow")


# --- AgentExecution.result ---


# Caps for the two web-coding hand-off fields (BE-8003j). A git branch ref is
# bounded well under 255 chars; a PR URL matches the 2048 cap used for redirect
# URIs. Both are agent-supplied via complete_job(result=...), so they carry the
# no-unvalidated-agent-input cap.
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
    """Validate agent_executions.result at the complete_job write boundary (BE-3006d).

    The agent-supplied ``result`` dict from complete_job() lands in the
    ``agent_executions.result`` JSONB column. ``AgentExecutionResult`` is
    ``extra="allow"`` — the blob is genuinely extensible (callers also pass
    ``files_changed`` / ``decisions_made`` and other ad-hoc keys) — so this gate
    only type-checks the known fields (``summary`` / ``artifacts`` / ``commits`` /
    ``branch`` / ``pr_url``) and returns the ORIGINAL payload unchanged on success
    (no reshaping, no dropped extras). Raises ``pydantic.ValidationError`` when a
    known field is the wrong type or an agent-supplied string exceeds its cap,
    which the MCP boundary surfaces as a clean 422-style error rather than letting
    a malformed blob reach the column.
    """
    AgentExecutionResult(**data)
    return data


# --- Product.product_memory ---


class ProductMemoryConfig(BaseModel):
    """Validates products.product_memory JSONB.

    BE-9261: seed key renamed github -> git_integration. github stays a
    declared field for READ tolerance of pre-rename rows only.
    """

    model_config = ConfigDict(extra="allow")

    git_integration: dict | None = None
    github: dict | None = None
    context: dict | None = None


# --- Product.tuning_state ---


class ProductTuningState(BaseModel):
    """Validates products.tuning_state JSONB."""

    model_config = ConfigDict(extra="allow")

    last_tuned_at: str | None = None
    last_tuned_at_sequence: int | None = None


# --- User.setup_selected_tools ---


class SetupSelectedTools(BaseModel):
    """Validates users.setup_selected_tools JSONB.

    List of AI coding tool names selected during setup wizard.
    Known values: claude, codex, gemini, etc.
    """

    items: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("items")
    @classmethod
    def validate_items(cls, v: list[str]) -> list[str]:
        for item in v:
            if len(item) > 200:
                raise ValueError(f"Tool name exceeds 200 characters: {item[:20]}...")
        return v


# --- User.notification_preferences ---


class NotificationPreferences(BaseModel):
    """Validates users.notification_preferences JSONB.

    Known schema with two fields. No extra fields allowed —
    the schema is fully defined by DEFAULT_NOTIFICATION_PREFERENCES.
    """

    model_config = ConfigDict(extra="forbid")

    context_tuning_reminder: bool = True
    tuning_reminder_threshold: int = Field(default=10, ge=3, le=1000)


# --- APIKey.permissions ---


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


# --- OAuthClient.redirect_uris (SaaS, API-0021c) ---


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


# --- MCPContextIndex.keywords ---


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


# --- Convenience validators ---


GIT_LOG_TITLED_COMMAND_HINT = "git log --format='%H%x09%s%x09%an' <base>..HEAD"


class GitCommitTitleRequiredError(ValueError):
    """Raised by validate_git_commits when a commit entry has no title.

    BE-9256: a title-less SHA-only string (or empty message/subject) was
    previously normalized to ``{"sha": ..., "message": ""}``, rendering a
    blank title on every UI surface. Fails closed instead, with the exact
    command to self-correct.
    """

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
    """Parse one ``<sha>\\t<subject>\\t<author>`` porcelain line (author optional).

    Matches the output of ``git log --format='%H%x09%s%x09%an'``.
    """
    parts = line.split("\t")
    sha = parts[0].strip() if parts else ""
    message = parts[1].strip() if len(parts) > 1 else ""
    author = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
    parsed: dict[str, str] = {"sha": sha, "message": message}
    if author:
        parsed["author"] = author
    return parsed


def validate_git_commits(data: list | None) -> list | None:
    """Validate git_commits array (BE-9256: fail closed on a missing commit title).

    Each entry must be EITHER a dict ``{"sha", "message", "author"?, "pr_url"?,
    ...}`` with a non-empty ``message``, OR a tab-delimited porcelain string
    ``"<sha>\\t<subject>\\t<author>"`` (author optional), parsed into that dict
    shape. A plain SHA-only string (no tabs) or any empty title raises
    ``GitCommitTitleRequiredError`` (BE-6208a used to silently normalize such
    a string to an empty-titled entry -- fixed here). Empty list / ``None``
    stays valid (the non-git-repo escape hatch is untouched).
    """
    if data is None:
        return None
    normalized: list = []
    for entry in data:
        if isinstance(entry, str):
            # rstrip \r\n only -- a full .strip() let a leading tab (empty sha) through (BE-9256 #2).
            raw = entry.rstrip("\r\n")
            if "\t" not in raw:
                # Plain SHA-only string (no tabs) -- the exact pre-BE-9256 empty-title shape.
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
    """Validate product_memory dict."""
    if data is None:
        return None
    return ProductMemoryConfig(**data).model_dump(exclude_none=False)


def validate_tuning_state(data: dict | None) -> dict | None:
    """Validate tuning_state dict."""
    if data is None:
        return None
    return ProductTuningState(**data).model_dump(exclude_none=False)


def validate_behavioral_rules(data: list | None) -> list | None:
    """Validate agent_templates.behavioral_rules — must be a list of strings."""
    if data is None:
        return None
    validated = []
    for item in data:
        if not isinstance(item, str):
            raise TypeError(f"behavioral_rules items must be strings, got {type(item).__name__}")
        validated.append(item)
    return validated


def validate_success_criteria(data: list | None) -> list | None:
    """Validate agent_templates.success_criteria — must be a list of strings."""
    if data is None:
        return None
    validated = []
    for item in data:
        if not isinstance(item, str):
            raise TypeError(f"success_criteria items must be strings, got {type(item).__name__}")
        validated.append(item)
    return validated


# --- UserApproval JSONB columns (BE-5029 Phase A) ---


class UserApprovalOption(BaseModel):
    """Validates one entry in user_approvals.options."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=100)
    label: str = Field(..., min_length=1, max_length=200)


def validate_user_approval_options(data: list[dict]) -> list[dict]:
    """Validate user_approvals.options at the service write boundary.

    Raises pydantic.ValidationError on shape mismatch and ValueError on duplicate ids.
    """
    if not isinstance(data, list) or not data:
        raise ValueError("options must be a non-empty list")
    validated = [UserApprovalOption(**opt).model_dump() for opt in data]
    ids = [opt["id"] for opt in validated]
    if len(ids) != len(set(ids)):
        raise ValueError("options must have unique ids")
    return validated


def validate_user_approval_context(data: dict | None) -> dict | None:
    """Validate user_approvals.context at the service write boundary.

    Context is intentionally extensible (deferred-findings payloads vary), but
    must be a JSON-serializable dict (or None) and must not exceed a soft size cap.
    """
    if data is None:
        return None
    if not isinstance(data, dict):
        raise TypeError("context must be a dict or None")
    # Soft cap: keep context payloads small enough that JSONB indexes stay healthy.
    # 16 KB serialized is generous for any realistic deferred-findings list.
    import json

    serialized = json.dumps(data)
    if len(serialized) > 16_384:
        raise ValueError("context exceeds 16384 byte soft cap")
    return data


# --- New convenience validators (sprint 002) ---


def validate_setup_selected_tools(data: list | None) -> list | None:
    """Validate User.setup_selected_tools — list of tool name strings."""
    if data is None:
        return None
    return SetupSelectedTools(items=data).items


def validate_notification_preferences(data: dict | None) -> dict | None:
    """Validate User.notification_preferences dict."""
    if data is None:
        return None
    return NotificationPreferences(**data).model_dump()


def validate_api_key_permissions(data: list | None) -> list | None:
    """Validate APIKey.permissions — list of permission strings."""
    if data is None:
        return None
    return APIKeyPermissions(items=data).items


def validate_context_keywords(data: list | None) -> list | None:
    """Validate MCPContextIndex.keywords — list of keyword strings."""
    if data is None:
        return None
    return ContextIndexKeywords(items=data).items


def validate_oauth_client_redirect_uris(data: list) -> list[str]:
    """Validate OAuthClient.redirect_uris — list of registered URIs.

    Required (non-empty) per RFC 7591 §2; max 10 entries to keep storage
    bounded. Scheme/host policy is enforced separately at the service
    layer where dev-vs-prod posture (allow http://localhost) is known.
    """
    return OAuthClientRedirectUris(items=data).items


def validate_string_list(
    data: list | None,
    field_name: str,
    max_items: int = 1000,
    max_length: int = 5000,
) -> list | None:
    """Generic validator for JSONB columns storing list[str].

    Used for ProductMemoryEntry list columns: key_outcomes, decisions_made,
    deliverables, tags.

    Args:
        data: List to validate, or None.
        field_name: Column name for error messages.
        max_items: Maximum number of items allowed.
        max_length: Maximum character length per item.

    Returns:
        Validated list or None.

    Raises:
        TypeError: If any item is not a string.
        ValueError: If list exceeds max_items or item exceeds max_length.
    """
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


# --- update_product_context MCP tool payloads (BE-5117) ---

# Runaway-agent tripline, NOT a product limit. Ingest auto-chunks documents and
# delivery paginates summaries, so legitimate light/medium summaries can exceed
# 50K chars; the only job of this bound is to stop a broken agent from OOMing
# Postgres TOAST with an unbounded blob.
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
    """Validate update_product_context(vision_summaries=[...]) input.

    Returns None for None input. Otherwise returns a list of dicts with
    keys {doc_id, light, medium}. Raises pydantic.ValidationError or
    ValueError on shape mismatch / length cap / duplicate doc_id.
    """
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
    """Validate update_product_context(consolidated_vision={...}) input."""
    if data is None:
        return None
    if not isinstance(data, dict):
        raise TypeError("consolidated_vision must be a dict with keys {light, medium}")
    return ConsolidatedVisionPayload(**data).model_dump()


# --- SequenceRun JSONB columns (BE-6131a) ---


class SequenceRunProjectIds(BaseModel):
    """Validates sequence_runs.project_ids — ordered list of project_id strings."""

    items: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("items")
    @classmethod
    def validate_items(cls, v: list[str]) -> list[str]:
        for item in v:
            if not isinstance(item, str):
                raise TypeError(f"project_ids items must be strings, got {type(item).__name__}")
            if len(item) > 36:
                raise ValueError(f"project_id exceeds 36 characters: {item[:36]!r}")
        return v


class SequenceRunProjectStatuses(BaseModel):
    """Validates sequence_runs.project_statuses — dict of project_id -> status string.

    Field names match actual DB key shape: arbitrary project_id strings as keys.
    extra='allow' because the keyset is dynamic (one key per project in the run).
    Status values are membership-validated against VALID_PROJECT_STATUSES.
    """

    model_config = ConfigDict(extra="allow")

    @classmethod
    def validate_map(cls, data: dict) -> dict:
        from giljo_mcp.models.sequence_runs import VALID_PROJECT_STATUSES

        for project_id, status in data.items():
            if not isinstance(project_id, str):
                raise TypeError(f"project_statuses keys must be strings, got {type(project_id).__name__}")
            if len(project_id) > 36:
                raise ValueError(f"project_id key exceeds 36 characters: {project_id[:36]!r}")
            if status not in VALID_PROJECT_STATUSES:
                raise ValueError(
                    f"project_statuses[{project_id!r}]: invalid status {status!r}. "
                    f"Valid: {sorted(VALID_PROJECT_STATUSES)}"
                )
        return data


class SequenceRunReviewedProjectIds(BaseModel):
    """Validates sequence_runs.reviewed_project_ids — list of reviewed member project_ids.

    A reviewed set is a subset of the run's members (cap MAX_SEQUENCE_PROJECTS=5),
    so it is length-capped identically to project_ids. Items are project-id strings
    (<= 36 chars). BE-9098.
    """

    items: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("items")
    @classmethod
    def validate_items(cls, v: list[str]) -> list[str]:
        for item in v:
            if not isinstance(item, str):
                raise TypeError(f"reviewed_project_ids items must be strings, got {type(item).__name__}")
            if len(item) > 36:
                raise ValueError(f"reviewed project_id exceeds 36 characters: {item[:36]!r}")
        return v


def validate_sequence_run_project_ids(data: list | None) -> list | None:
    """Validate sequence_runs.project_ids at the service write boundary."""
    if data is None:
        return None
    return SequenceRunProjectIds(items=data).items


def validate_sequence_run_reviewed_project_ids(data: list | None) -> list | None:
    """Validate sequence_runs.reviewed_project_ids at the service write boundary."""
    if data is None:
        return None
    return SequenceRunReviewedProjectIds(items=data).items


def validate_sequence_run_project_statuses(data: dict | None) -> dict | None:
    """Validate sequence_runs.project_statuses at the service write boundary."""
    if data is None:
        return None
    if not isinstance(data, dict):
        raise TypeError("project_statuses must be a dict")
    return SequenceRunProjectStatuses.validate_map(data)


# --- AccountDeletionRequest.billing_cancel_response (SEC-5105b / BE-5108) ---


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


# --- DeletionReceipt.storage_object_key_sha256s (BE-9040 fix, reviewer WARN) ---
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
