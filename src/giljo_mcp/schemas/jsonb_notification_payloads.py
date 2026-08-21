# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Pydantic validation models for ``Notification.payload`` and system banners.

Extracted from ``jsonb_validators.py`` (INF-6132) to keep that module under the
800-line file-size guardrail. These payload schemas are a cohesive unit: each is
keyed by a ``Notification.type`` discriminator in
``NOTIFICATION_PAYLOAD_VALIDATORS`` and validated at the
``NotificationService.create`` write boundary. The registry is shared so the
SaaS edition can register its own banner payloads via
``register_notification_payload_validators`` without any CE module importing
``saas/`` code.

The names defined here are re-exported from ``jsonb_validators`` for backward
compatibility, so existing imports keep working unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# --- Notification.payload (IMP-5037a) ---
#
# Registry keyed by Notification.type -> payload schema, called at the
# NotificationService.create write boundary. Field names match the actual
# payload keys the consumer (frontend bell) and emitters (e.g. the API-key
# expiry scan) read/write. Unknown types raise — a notification type without a
# registered payload schema is a programming error, not a runtime fallback.


class ApiKeyExpiringSoonPayload(BaseModel):
    """Validates payload for Notification.type == "api_key.expiring_soon".

    Emitted by AuthService.scan_expiring_api_keys. Carries the fields the bell
    needs to render the row and link the user to the affected key.
    """

    model_config = ConfigDict(extra="forbid")

    api_key_id: str = Field(..., min_length=1, max_length=36)
    name: str = Field(..., min_length=1, max_length=255)
    expires_at: str = Field(..., min_length=1, max_length=64)


# --- System banner payloads (IMP-5037b, CE) ---


class PendingMigrationsPayload(BaseModel):
    """Validates payload for Notification.type == "system.pending_migrations".

    Emitted at startup when the DB schema is behind the bundled migration head.
    ``pending`` is the number of un-applied revisions; ``head`` is the bundled
    head revision id the running code expects.
    """

    model_config = ConfigDict(extra="forbid")

    pending: int = Field(..., ge=0)
    head: str = Field(..., min_length=1, max_length=255)


class UpdateAvailablePayload(BaseModel):
    """Validates payload for Notification.type == "system.update_available".

    Emitted by the 6-hourly update checker. ``commits_behind`` is set for git
    installs; ``release_url`` / ``tag`` are set for release-zip installs. All
    optional so either install strategy can populate only its relevant fields.
    """

    model_config = ConfigDict(extra="forbid")

    commits_behind: int | None = Field(default=None, ge=0)
    release_url: str | None = Field(default=None, max_length=2048)
    tag: str | None = Field(default=None, max_length=128)


class SkillsDriftPayload(BaseModel):
    """Validates payload for Notification.type == "system.skills_drift".

    Emitted when the bundled SKILLS_VERSION the running server ships with has
    moved ahead of the operator-announced version. ``current`` is the bundled
    constant; ``announced`` is the last announced value (may be None).
    """

    model_config = ConfigDict(extra="forbid")

    current: str = Field(..., min_length=1, max_length=128)
    announced: str | None = Field(default=None, max_length=128)
    message: str | None = Field(default=None, max_length=512)


class ToolRenameNoticePayload(BaseModel):
    """Validates payload for Notification.type == "system.tool_rename_notice".

    INF-6049a one-time CE migration prompt (get_orchestrator_instructions ->
    get_staging_instructions), shown for the first few process boots after the rename.
    The notice carries no structured payload; everything the user needs is in the
    title/body, so the payload is an empty (extra-forbidding) object.
    """

    model_config = ConfigDict(extra="forbid")


class ContextTuningDuePayload(BaseModel):
    """Validates payload for Notification.type == "system.context_tuning_due".

    FE-9202: emitted by the periodic system-banner refresh when the active
    product has not had its context tuned in 14+ days AND at least one project
    has completed since the last tune (the activity gate). Carries the product
    identity the banner renders and links back to. ``projects_since_tune`` is the
    completed-project count since the last tune (the activity signal).
    """

    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(..., min_length=1, max_length=36)
    product_name: str = Field(..., min_length=1, max_length=255)
    projects_since_tune: int = Field(..., ge=0)


class ProjectPrelaunchWorkproductPayload(BaseModel):
    """Validates payload for Notification.type == "project.pre_launch_workproduct".

    BE-9085: emitted by the closeout-hook detector in write_memory_entry.py
    when a project_completion closeout carries git commits while the
    project's Implement-gate (``implementation_launched_at``) was never
    approved this cycle. Alarm-only -- carries enough for the bell/banner
    to render and link back to the project; the closeout itself is never
    blocked or altered by this detector (fail-open).

    FE-9222: ``taxonomy_alias`` (the project's human tag, e.g. "PRJ-0042")
    enriches the row so the notification names the project unambiguously.
    Optional -- a project without a resolvable alias still emits.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1, max_length=36)
    project_name: str = Field(..., min_length=1, max_length=255)
    taxonomy_alias: str | None = Field(default=None, max_length=64)
    commit_count: int = Field(..., ge=0)


class CloseoutApprovalRequiredPayload(BaseModel):
    """Validates payload for Notification.type == "closeout.approval_required".

    BE-9153: emitted (surface="both") when the signal-gated closeout_mode gate
    auto-creates a user_approval — either a solo closeout block or a chain-link
    settlement approval. Carries enough for the bell/banner to render and link back
    to the project's approval card; the approval itself is the load-bearing record.

    BE-9436b: ``project_name`` names the project the closeout belongs to, so the
    row obeys the affiliated-name rule (names, never UUIDs) the way
    ``ProjectPrelaunchWorkproductPayload`` already does. OPTIONAL, unlike that
    sibling: the emitter is deliberately fail-open (a notification failure must
    never break the closeout gate), so a project whose name cannot be resolved
    must still produce a bell row rather than none at all. Rows written before
    this field existed simply lack the key — ``extra="forbid"`` forbids unknown
    keys, never absent ones, and the read path does not re-validate.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1, max_length=36)
    approval_id: str = Field(..., min_length=1, max_length=36)
    reason_count: int = Field(..., ge=0)
    project_name: str | None = Field(default=None, max_length=255)


class HubBatonHandoverPayload(BaseModel):
    """Validates payload for Notification.type == "hub.baton_handover".

    BE-9296a: emitted when a Hub baton is handed to the OPERATOR. FE-9289c already
    drops a bell entry from the live WebSocket event, but that entry is client-local
    (localStorage), so a hand-off that arrives while the dashboard is closed — or on
    a different device — was simply never seen. This is the durable server row that
    survives a reload and reaches a second browser.

    Carries what the bell needs to render the row and route back to the thread:
    ``chat_id`` is the human-facing CHT-#### serial, ``handed_by`` is the SERVER-
    resolved display name of whoever handed over (never self-declared text).
    """

    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(..., min_length=1, max_length=36)
    chat_id: str = Field(..., min_length=1, max_length=64)
    handed_by: str | None = Field(default=None, max_length=200)


NOTIFICATION_PAYLOAD_VALIDATORS: dict[str, type[BaseModel]] = {
    "api_key.expiring_soon": ApiKeyExpiringSoonPayload,
    "system.pending_migrations": PendingMigrationsPayload,
    "system.update_available": UpdateAvailablePayload,
    "system.skills_drift": SkillsDriftPayload,
    "system.tool_rename_notice": ToolRenameNoticePayload,
    "system.context_tuning_due": ContextTuningDuePayload,
    "project.pre_launch_workproduct": ProjectPrelaunchWorkproductPayload,
    "closeout.approval_required": CloseoutApprovalRequiredPayload,
    "hub.baton_handover": HubBatonHandoverPayload,
}


def register_notification_payload_validators(validators: dict[str, type[BaseModel]]) -> None:
    """Register additional Notification payload validators into the shared registry.

    Used by the SaaS edition (imported only under ``GILJO_MODE=saas``) to add
    its banner payload schemas without the CE module importing any ``saas/``
    code. The registry itself is shared; the SaaS schema *definitions* stay
    edition-isolated. Idempotent — re-registering the same type is a no-op
    overwrite with the identical schema.
    """
    NOTIFICATION_PAYLOAD_VALIDATORS.update(validators)


def validate_notification_payload(notification_type: str, data: dict | None) -> dict:
    """Validate a Notification.payload by its ``type`` discriminator.

    Returns the validated payload as a dict. Raises KeyError if ``type`` has no
    registered payload schema (caller passed an unknown notification type), or
    pydantic.ValidationError on shape mismatch.
    """
    if notification_type not in NOTIFICATION_PAYLOAD_VALIDATORS:
        raise KeyError(f"No payload validator registered for notification type: {notification_type}")
    schema = NOTIFICATION_PAYLOAD_VALIDATORS[notification_type]
    return schema(**(data or {})).model_dump()
