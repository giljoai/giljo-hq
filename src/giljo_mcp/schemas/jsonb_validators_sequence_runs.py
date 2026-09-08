# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Pydantic validation models for ``SequenceRun`` (sequence_runs) JSONB columns.

Extracted from ``jsonb_validators.py`` (BE-9540 cleanup, mirroring the earlier
BE-9040 settings extraction) to keep that module under the 800-line file-size
guardrail. Each model here validates one ``sequence_runs`` JSONB column at the
``SequenceRunService`` write boundary (BE-6131a).

The names defined here are re-exported from ``jsonb_validators`` for backward
compatibility, so existing imports keep working unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


VALID_REVIEWED_VIA: frozenset[str] = frozenset({"ui", "harness"})


class SequenceRunReviewedVia(BaseModel):
    """Validates sequence_runs.reviewed_via — {project_id -> "ui" | "harness"}.

    Per-member review PROVENANCE (BE-9540), mirroring UserApproval.decided_via's
    "which door" shape. Keys are a subset of reviewed_project_ids (cap
    MAX_SEQUENCE_PROJECTS=5, same bound); values are membership-validated against
    VALID_REVIEWED_VIA. Field names match the actual DB key shape (arbitrary
    project_id strings as keys), so extra='allow' like SequenceRunProjectStatuses.
    """

    model_config = ConfigDict(extra="allow")

    @classmethod
    def validate_map(cls, data: dict) -> dict:
        if len(data) > 5:
            raise ValueError(f"reviewed_via has {len(data)} entries, exceeds cap of 5")
        for project_id, via in data.items():
            if not isinstance(project_id, str):
                raise TypeError(f"reviewed_via keys must be strings, got {type(project_id).__name__}")
            if len(project_id) > 36:
                raise ValueError(f"project_id key exceeds 36 characters: {project_id[:36]!r}")
            if via not in VALID_REVIEWED_VIA:
                raise ValueError(f"reviewed_via value must be one of {sorted(VALID_REVIEWED_VIA)}, got {via!r}")
        return data


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


def validate_sequence_run_reviewed_via(data: dict | None) -> dict | None:
    """Validate sequence_runs.reviewed_via at the service write boundary."""
    if data is None:
        return None
    if not isinstance(data, dict):
        raise TypeError("reviewed_via must be a dict")
    return SequenceRunReviewedVia.validate_map(data)


def validate_sequence_run_project_statuses(data: dict | None) -> dict | None:
    """Validate sequence_runs.project_statuses at the service write boundary."""
    if data is None:
        return None
    if not isinstance(data, dict):
        raise TypeError("project_statuses must be a dict")
    return SequenceRunProjectStatuses.validate_map(data)
