# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Request models for the user endpoints.

Companion to ``auth_models.py``, and it exists for the same two reasons: the
endpoint module is on the repo's shrink-only size budget, and a request shape
is a contract worth reading on its own rather than buried between handlers.

**Edition Scope:** Both
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NotificationPreferencesUpdate(BaseModel):
    """A partial update to the current user's notification preferences.

    FE-9553: the PUT used to take a bare ``dict[str, Any]``, so every field
    reached the service unvalidated and a bad value surfaced as a 500 out of the
    JSONB validator rather than a 422 at the door. The house rule is explicit
    that a database constraint is not an input gate -- "constraints produce
    500s, not 422s" -- so the shape is declared here.

    Every field is OPTIONAL and the handler sends only what was actually set:
    an absent key means "leave it alone", which is the semantics the service's
    per-key guards already implement. That is why this model cannot carry
    defaults -- defaults would turn an absent key into an explicit write of the
    default value, quietly resetting preferences the caller never mentioned.

    Decisions, your-turn batons and mentions are deliberately absent from this
    model. They are always-on by ruling, because a settings surface must never
    be able to unplug the doorbell for a decision the system is blocked on, so
    the settings card states that in text rather than offering a switch that
    must never be flipped.
    """

    model_config = ConfigDict(extra="forbid")

    context_tuning_reminder: bool | None = None
    tuning_reminder_threshold: int | None = Field(default=None, ge=3, le=1000)
    banner_lifecycle_enabled: bool | None = None
    banner_advisories_in_fold: bool | None = None
    popout_scope: Literal["all", "actionable", "off"] | None = None

    @model_validator(mode="before")
    @classmethod
    def _refuse_explicit_nulls(cls, data: Any) -> Any:
        """An explicitly sent ``null`` is a client error, not "leave it alone".

        The ``| None`` on every field expresses OPTIONALITY, and
        ``exclude_unset`` is what distinguishes absent from set. But that leaves
        an explicit ``{"popout_scope": null}`` as a set-to-None, which sails
        through the field types and fails deeper down in the JSONB validator --
        as a 500, which is exactly what declaring this model was meant to
        prevent. A test caught that before it shipped; this is the fix.

        Refusing rather than ignoring, on purpose: silently dropping a null
        would answer 200 to a request that changed nothing, which reads as
        success and is the kind of quiet near-miss that is worse than an error.
        """
        if isinstance(data, dict):
            nulls = sorted(key for key, value in data.items() if value is None)
            if nulls:
                raise ValueError(
                    f"these fields were sent as null, which is not a value: {', '.join(nulls)}. "
                    "Omit a field entirely to leave it unchanged."
                )
        return data
