# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9408: one line saying where an orchestrator identity came from.

A saved override silently replaces the built-in identity, survives every restart (it
is data, not deployment), spans every product when tenant-scoped, and nothing ever
said so. Three incidents were diagnosed by hand for want of this line. It ships with
the identity itself -- not in a log, not in a dashboard -- because the reader who
needs it is the agent wearing the persona, and the operator reading that agent's
transcript afterwards.

Pure: no I/O, no session, no service. Both identity paths (the get_job_mission
resolver and the staging read) call it, so the two surfaces cannot word the same
override differently -- which would put an operator comparing two transcripts back
where they started.

Edition Scope: Both.
"""

from __future__ import annotations

from datetime import datetime

from giljo_mcp.system_prompts.service import SCOPE_PRODUCT, SCOPE_TENANT


_PREFIX = "identity source:"


def format_identity_source(
    scope: str,
    *,
    updated_at: datetime | None = None,
    product_name: str | None = None,
) -> str:
    """Render the provenance line for one resolved rung.

    The three shapes, in the wording the project pinned::

        identity source: tenant-wide override, saved 2026-07-16
        identity source: product override (Acme Widgets), saved 2026-07-16
        identity source: built-in default

    Deliberately NEUTRAL about whose product it is. The dedicated chain conductor
    resolves its product through its run's HEAD project rather than through a project
    of its own (it has none), so wording like "your project's product" would be a lie
    on exactly the surface where a chain persona mismatch is hardest to spot.

    Degradation, when the data behind a real override row is incomplete: drop the
    clause rather than assert something false. A row whose stored timestamp did not
    parse yields ``identity source: tenant-wide override`` -- still the answer to
    "is this the built-in?", which is the question that matters -- rather than
    ``saved None``. Same for a product whose name could not be read.
    """
    if scope == SCOPE_TENANT:
        return f"{_PREFIX} tenant-wide override{_saved_clause(updated_at)}"
    if scope == SCOPE_PRODUCT:
        named = f" ({product_name})" if product_name else ""
        return f"{_PREFIX} product override{named}{_saved_clause(updated_at)}"
    return f"{_PREFIX} built-in default"


def append_identity_source(identity_text: str, source_line: str) -> str:
    """Append the provenance line to composed identity text.

    The separator lives here, in one place, because the content-unchanged pin is
    stated in terms of it: served identity must equal the composed identity plus
    exactly this delta. Two paths append; if they drifted apart, one of them would
    quietly stop matching that pin.
    """
    return f"{identity_text}\n\n{source_line}"


def _saved_clause(updated_at: datetime | None) -> str:
    """``, saved YYYY-MM-DD``, or nothing at all when there is no usable date."""
    if updated_at is None:
        return ""
    return f", saved {updated_at.strftime('%Y-%m-%d')}"
