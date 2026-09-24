# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.handover_validation import REQUIRED_HANDOVER_HEADINGS, missing_handover_headings


HANDOVER_TEMPLATE_SETTING_KEY = "handover_template"

HANDOVER_TEMPLATE_FIELD = "handover_template"
HANDOVER_TEMPLATE_LENGTH_CONSTRAINT = "max_length"

HANDOVER_TEMPLATE_MAX_CHARS = 8000

DEFAULT_HANDOVER_TEMPLATE = """<2-3 sentences: what this session covered, why the handoff is happening, and the
most critical thing your successor must know first.>

<Team state: name the agents, their statuses, what each is waiting on. Name the
in-progress work and exactly where you stopped.>

## Verify before trusting
- <claim> -- check with: <the exact command that checks it, and what a pass prints>

## Waiting on the operator
- <what cannot move without a human, who from, and what is blocked until it arrives; "nothing" if there is none>

## Cannot testify
- <what you did NOT verify, and why; "nothing" only if that is genuinely true>

## References
- <paths or links to reports, one per line>
"""


def normalize_handover_template(template: str | None) -> str:
    text = (template or "").rstrip()
    missing = missing_handover_headings(text)
    if not missing:
        return template or ""

    appended = "\n\n".join(f"{heading}\n- <fill this in>" for heading in missing)
    if not text:
        return appended + "\n"
    return f"{text}\n\n{appended}\n"


def require_template_within_cap(template: str, *, operation: str) -> None:
    if len(template) <= HANDOVER_TEMPLATE_MAX_CHARS:
        return
    raise ValidationError(
        message=(
            f"The handover template is {len(template)} characters, over the "
            f"{HANDOVER_TEMPLATE_MAX_CHARS}-character limit, so it was not saved. It is copied "
            "into every handover prompt this account generates, which is what the limit "
            "protects. Shorten it, or move the long parts into a document and link them "
            "under a references section."
        ),
        context={
            "operation": operation,
            "field": HANDOVER_TEMPLATE_FIELD,
            "constraint": HANDOVER_TEMPLATE_LENGTH_CONSTRAINT,
            "max_length": HANDOVER_TEMPLATE_MAX_CHARS,
            "length": len(template),
        },
    )


def resolve_handover_template(stored: str | None) -> str:
    if not (stored or "").strip():
        return DEFAULT_HANDOVER_TEMPLATE
    return normalize_handover_template(stored)


def template_is_default(stored: str | None) -> bool:
    return resolve_handover_template(stored) == DEFAULT_HANDOVER_TEMPLATE


__all__ = [
    "DEFAULT_HANDOVER_TEMPLATE",
    "HANDOVER_TEMPLATE_FIELD",
    "HANDOVER_TEMPLATE_LENGTH_CONSTRAINT",
    "HANDOVER_TEMPLATE_MAX_CHARS",
    "HANDOVER_TEMPLATE_SETTING_KEY",
    "REQUIRED_HANDOVER_HEADINGS",
    "normalize_handover_template",
    "require_template_within_cap",
    "resolve_handover_template",
    "template_is_default",
]
