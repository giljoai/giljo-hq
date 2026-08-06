# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Shared unknown-key reporting for agent-facing tool boundaries (BE-9322).

One rule: **no caller-supplied key is discarded silently.** Every boundary
names back what it could not use, at the strongest enforcement that boundary
is capable of.

The two current callers enforce it at different strengths, and the difference
is forced by capability rather than taste:

* ``get_context`` **raises** -- its sibling ``categories`` argument already
  rejects unknown values, so silently defaulting an unknown ``depth_config``
  key was the odd one out. A depth key is the DB column name
  (``memory_last_n_projects``) about half the time and the category name
  (``memory_360``) the other half; the wrong one used to apply the default
  while ``depth_config_applied`` truthfully reported that default, so nothing
  in the response named the dropped key.
* ``update_product_context`` **reports** into its existing ``fields_skipped``.
  It cannot raise on a genuinely unknown top-level argument, because FastMCP
  builds its argument model from the fixed tool signature and Pydantic's
  default ``extra="ignore"`` drops anything unrecognised before the tool
  function is entered. A boundary cannot reject what it never receives.
"""

from collections.abc import Collection
from typing import Any


def split_known(supplied: dict[str, Any], known: Collection[str]) -> tuple[dict[str, Any], list[str]]:
    """Partition ``supplied`` into the recognised subset and the unknown names.

    Args:
        supplied: Caller-provided mapping (never mutated).
        known: The accepted key vocabulary.

    Returns:
        ``(used, unknown)`` -- ``used`` keeps only recognised keys; ``unknown``
        is the sorted list of names that were not recognised, suitable for
        putting straight into an error message or a ``*_skipped`` field.
    """
    used = {key: value for key, value in supplied.items() if key in known}
    unknown = sorted(key for key in supplied if key not in known)
    return used, unknown
