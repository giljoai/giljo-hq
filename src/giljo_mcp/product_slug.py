# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""The product's URL-safe short name, used to qualify exported agent filenames.

BE-9385b. Exported agents are named ``<agent-name>--<product-slug>.md`` so the
same agent, shared by two products, installs twice instead of overwriting itself.
That only works if the slug is **stable** and **unique**, which is why
``products.slug`` is a persisted column rather than something derived at render
time:

* **Stable** -- it is generated once at creation and NEVER rewritten, so renaming
  a product does not rename every file the user has already installed.
* **Unique** -- a partial unique index on ``(tenant_key, slug)`` makes a collision
  impossible by construction rather than by discipline. Two products called
  "Acme Corp" and "Acme-Corp" slugify identically; the de-duplicating suffix
  applied at creation (and by the ce_0092 backfill) is what keeps them apart.

This module holds only the pure text transform. Allocation of a unique slug is
the owning service's job (``ProductService.create_product``), because uniqueness
is a database question and this function cannot see the database.
"""

from __future__ import annotations

import re


# Long enough to stay readable inside a filename next to an agent name, short
# enough that ``<agent-name>--<product-slug>.md`` cannot approach a path limit on
# any platform we install into.
MAX_SLUG_LENGTH = 48

# What a slug looks like when the name contributes nothing usable -- a product
# named "..." or "###" still needs a filename component.
FALLBACK_SLUG = "product"

_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")


def slugify_product_name(name: str | None) -> str:
    """Return the URL-safe slug base for ``name``.

    Deterministic and total: every input yields a non-empty slug matching
    ``[a-z0-9][a-z0-9-]*``. Callers append their own de-duplicating suffix; this
    function knows nothing about other products.

    Args:
        name: The product's display name. ``None`` and blank are accepted rather
            than rejected -- this runs on a legacy-row fallback path where the
            caller cannot guarantee a name, and raising there would break an
            export over cosmetics.

    Returns:
        A slug of at most :data:`MAX_SLUG_LENGTH` characters, or
        :data:`FALLBACK_SLUG` when the name contributes no usable characters.
    """
    slug = _NON_SLUG_CHARS.sub("-", (name or "").strip().lower()).strip("-")
    if not slug:
        return FALLBACK_SLUG
    # Truncate, then re-strip: cutting at the limit can leave a trailing hyphen,
    # which would render as "agent--acme-.md".
    return slug[:MAX_SLUG_LENGTH].strip("-") or FALLBACK_SLUG


__all__ = ["FALLBACK_SLUG", "MAX_SLUG_LENGTH", "slugify_product_name"]
