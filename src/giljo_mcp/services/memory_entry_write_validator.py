# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


MEMORY_SUMMARY_MAX = 1500
MEMORY_KEY_OUTCOME_MAX = 250
MEMORY_KEY_OUTCOMES_COUNT = 5
MEMORY_DECISION_MAX = 250
MEMORY_DECISIONS_COUNT = 5
MEMORY_DELIVERABLES_COUNT = 3
MEMORY_DELIVERABLE_MAX = 100
MEMORY_TAG_MAX_LEN = 30
MEMORY_TAGS_COUNT = 8


CONTROLLED_TAG_VOCABULARY: frozenset[str] = frozenset(
    {
        "feature",
        "bug-fix",
        "refactor",
        "perf",
        "security",
        "docs",
        "test",
        "chore",
        "frontend",
        "backend",
        "database",
        "api",
        "infrastructure",
        "ui-ux",
        "integration",
        "migration",
    }
)


class _UnknownTagError(ValueError):

    def __init__(self, tag: str):
        self.tag = tag
        super().__init__(f"tag '{tag}' is not in the controlled vocabulary")


def _validate_tag_token(tag: str) -> str:
    if not isinstance(tag, str):
        raise ValueError("tag must be a string")  # noqa: TRY004
    if len(tag) > MEMORY_TAG_MAX_LEN:
        raise ValueError(f"tag '{tag[:20]}...' exceeds {MEMORY_TAG_MAX_LEN} characters")
    if tag not in CONTROLLED_TAG_VOCABULARY:
        raise _UnknownTagError(tag)
    return tag


_TAG_GUIDANCE = (
    "Tags must come from the 16-entry controlled vocabulary. "
    "Pick 1-3 from change-type axis (feature/bug-fix/refactor/perf/security/docs/test/chore) "
    "AND 1-3 from domain axis (frontend/backend/database/api/infrastructure/ui-ux/integration). "
    "Use 'migration' for schema changes."
)


_GUIDANCE = {
    "summary": "Trim to 2-3 sentence headline of what changed and why. Detail belongs in commit messages.",
    "key_outcomes": (
        f"Cap is {MEMORY_KEY_OUTCOMES_COUNT} bullet outcomes, each <= {MEMORY_KEY_OUTCOME_MAX} chars. "
        "Merge or trim items, then retry."
    ),
    "decisions_made": (
        f"Cap is {MEMORY_DECISIONS_COUNT} architectural decisions, each <= {MEMORY_DECISION_MAX} chars. "
        "Move detail into commit messages or vision documents."
    ),
    "deliverables": (
        f"Cap is {MEMORY_DELIVERABLES_COUNT} deliverables, each <= {MEMORY_DELIVERABLE_MAX} chars. "
        "Deliverables is a drop-cap field (full removal scheduled post-demo) -- "
        "merge into key_outcomes if you have more."
    ),
    "tags": _TAG_GUIDANCE,
}


class MemoryEntryWriteValidationError(Exception):

    def __init__(
        self,
        *,
        field: str,
        actual_size: int,
        max_size: int,
        guidance: str,
        invalid_tag: str | None = None,
        allowed: list[str] | None = None,
        all_failures: list[dict[str, Any]] | None = None,
    ):
        self.error = "validation_failed"
        self.field = field
        self.actual_size = actual_size
        self.max_size = max_size
        self.guidance = guidance
        self.invalid_tag = invalid_tag
        self.allowed = allowed
        self.all_failures = all_failures
        super().__init__(f"validation_failed: {field} actual={actual_size} max={max_size} -- {guidance}")

    def __str__(self) -> str:
        line = self.args[0]
        if self.invalid_tag is not None:
            line += f" (invalid_tag={self.invalid_tag!r})"
        if self.allowed is not None:
            line += f" Allowed: {sorted(self.allowed)}."
        lines = [line]
        for idx, failure in enumerate(self.all_failures or ()):
            if idx == 0:
                continue
            other = (
                f"ALSO FAILED: {failure['field']} actual={failure['actual_size']} "
                f"max={failure['max_size']} -- {failure['guidance']}"
            )
            if failure.get("invalid_tag") is not None:
                other += f" (invalid_tag={failure['invalid_tag']!r})"
            if failure.get("allowed") is not None:
                other += f" Allowed: {sorted(failure['allowed'])}."
            lines.append(other)
        return " || ".join(lines)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error": self.error,
            "field": self.field,
            "actual_size": self.actual_size,
            "max_size": self.max_size,
            "guidance": self.guidance,
        }
        if self.invalid_tag is not None:
            payload["invalid_tag"] = self.invalid_tag
        if self.allowed is not None:
            payload["allowed"] = self.allowed
        if self.all_failures is not None:
            payload["all_failures"] = self.all_failures
        return payload


class MemoryEntryWriteSchema(BaseModel):
    """Pydantic write-side schema for product_memory_entries (INF-WriteShape).

    Used by ProductMemoryService.create_entry() before any DB write.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    summary: str = Field(..., max_length=MEMORY_SUMMARY_MAX)
    key_outcomes: list[str] = Field(default_factory=list, max_length=MEMORY_KEY_OUTCOMES_COUNT)
    decisions_made: list[str] = Field(default_factory=list, max_length=MEMORY_DECISIONS_COUNT)
    deliverables: list[str] = Field(default_factory=list, max_length=MEMORY_DELIVERABLES_COUNT)
    tags: list[str] = Field(default_factory=list, max_length=MEMORY_TAGS_COUNT)

    @field_validator("key_outcomes")
    @classmethod
    def _validate_key_outcomes_items(cls, v: list[str]) -> list[str]:
        for i, item in enumerate(v):
            if not isinstance(item, str):
                raise ValueError(f"key_outcomes[{i}] must be a string")  # noqa: TRY004
            if len(item) > MEMORY_KEY_OUTCOME_MAX:
                raise ValueError(f"key_outcomes[{i}] exceeds {MEMORY_KEY_OUTCOME_MAX} characters (got {len(item)})")
        return v

    @field_validator("decisions_made")
    @classmethod
    def _validate_decisions_items(cls, v: list[str]) -> list[str]:
        for i, item in enumerate(v):
            if not isinstance(item, str):
                raise ValueError(f"decisions_made[{i}] must be a string")  # noqa: TRY004
            if len(item) > MEMORY_DECISION_MAX:
                raise ValueError(f"decisions_made[{i}] exceeds {MEMORY_DECISION_MAX} characters (got {len(item)})")
        return v

    @field_validator("deliverables")
    @classmethod
    def _validate_deliverables_items(cls, v: list[str]) -> list[str]:
        for i, item in enumerate(v):
            if not isinstance(item, str):
                raise ValueError(f"deliverables[{i}] must be a string")  # noqa: TRY004
            if len(item) > MEMORY_DELIVERABLE_MAX:
                raise ValueError(f"deliverables[{i}] exceeds {MEMORY_DELIVERABLE_MAX} characters (got {len(item)})")
        return v

    @field_validator("tags")
    @classmethod
    def _validate_tags_items(cls, v: list[str]) -> list[str]:
        return [_validate_tag_token(t) for t in v]


def _translate_one(first: dict[str, Any], payload: dict[str, Any]) -> MemoryEntryWriteValidationError:
    loc = first.get("loc", ())
    field = str(loc[0]) if loc else "unknown"
    raw = payload.get(field)

    if field == "summary":
        return MemoryEntryWriteValidationError(
            field=field,
            actual_size=len(raw) if isinstance(raw, str) else 0,
            max_size=MEMORY_SUMMARY_MAX,
            guidance=_GUIDANCE["summary"],
        )

    cap_map = {
        "key_outcomes": (MEMORY_KEY_OUTCOMES_COUNT, MEMORY_KEY_OUTCOME_MAX),
        "decisions_made": (MEMORY_DECISIONS_COUNT, MEMORY_DECISION_MAX),
        "deliverables": (MEMORY_DELIVERABLES_COUNT, MEMORY_DELIVERABLE_MAX),
        "tags": (MEMORY_TAGS_COUNT, MEMORY_TAG_MAX_LEN),
    }
    if field == "tags":
        ctx = first.get("ctx") or {}
        underlying = ctx.get("error")
        invalid_tag: str | None = None
        if isinstance(underlying, _UnknownTagError):
            invalid_tag = underlying.tag
        elif isinstance(raw, list) and len(loc) > 1 and isinstance(loc[1], int) and 0 <= loc[1] < len(raw):
            candidate = raw[loc[1]]
            if isinstance(candidate, str) and candidate not in CONTROLLED_TAG_VOCABULARY:
                invalid_tag = candidate

        count_cap, item_cap = cap_map[field]
        if isinstance(raw, list) and len(raw) > count_cap:
            return MemoryEntryWriteValidationError(
                field=field,
                actual_size=len(raw),
                max_size=count_cap,
                guidance=_GUIDANCE[field],
            )
        if invalid_tag is not None:
            return MemoryEntryWriteValidationError(
                field=field,
                actual_size=len(invalid_tag),
                max_size=item_cap,
                guidance=_TAG_GUIDANCE,
                invalid_tag=invalid_tag,
                allowed=sorted(CONTROLLED_TAG_VOCABULARY),
            )
        return MemoryEntryWriteValidationError(
            field=field,
            actual_size=len(raw) if isinstance(raw, list) else 0,
            max_size=count_cap,
            guidance=_GUIDANCE[field],
        )

    if field in cap_map:
        count_cap, item_cap = cap_map[field]
        if isinstance(raw, list):
            if len(raw) > count_cap:
                return MemoryEntryWriteValidationError(
                    field=field,
                    actual_size=len(raw),
                    max_size=count_cap,
                    guidance=_GUIDANCE[field],
                )
            for item in raw:
                if isinstance(item, str) and len(item) > item_cap:
                    return MemoryEntryWriteValidationError(
                        field=field,
                        actual_size=len(item),
                        max_size=item_cap,
                        guidance=_GUIDANCE[field],
                    )
        return MemoryEntryWriteValidationError(
            field=field,
            actual_size=len(raw) if isinstance(raw, list) else 0,
            max_size=count_cap,
            guidance=_GUIDANCE[field],
        )

    return MemoryEntryWriteValidationError(field=field, actual_size=0, max_size=0, guidance=str(first.get("msg", "")))


def _translate_pydantic_error(exc: ValidationError, payload: dict[str, Any]) -> MemoryEntryWriteValidationError:
    errors = exc.errors()
    if not errors:
        return MemoryEntryWriteValidationError(
            field="unknown", actual_size=0, max_size=0, guidance="Validation failed (no error details)"
        )

    primary = _translate_one(errors[0], payload)

    seen_fields: set[str] = set()
    failures: list[dict[str, Any]] = []
    for err in errors:
        translated = _translate_one(err, payload)
        if translated.field in seen_fields:
            continue
        seen_fields.add(translated.field)
        failures.append(translated.to_dict())

    if len(failures) > 1:
        primary.all_failures = failures
    return primary


def validate_memory_entry_write(payload: dict[str, Any]) -> MemoryEntryWriteSchema:
    try:
        return MemoryEntryWriteSchema(**payload)
    except ValidationError as exc:
        raise _translate_pydantic_error(exc, payload) from exc
