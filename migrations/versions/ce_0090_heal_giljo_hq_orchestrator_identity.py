# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9361: heal the "GiljoAI MCP" -> "Giljo HQ" orchestrator identity prose.

Revision ID: ce_0090_heal_giljo_hq_orchestrator_identity
Revises: ce_0089_be9348_repair_absorbed_closeout_arguments
Create Date: 2026-08-03

BE-9361 swept the last "GiljoAI MCP" residuals out of agent- and user-facing
prose. One of them lives inside SEEDED template text: the orchestrator role's
``user_instructions`` identity sentence in ``template_seeder.py``
("You are the **Orchestrator Agent** for **GiljoAI MCP**"), now derived from
``branding.PRODUCT_NAME`` via ``_ORCHESTRATOR_IDENTITY_HEAD``.

Why this migration is defensive rather than load-bearing
========================================================
The orchestrator role is in ``SYSTEM_MANAGED_ROLES`` (``system_roles.py``) and
BOTH DB write paths skip it -- ``template_seeder._seed_tenant_templates`` and
``template_import`` each ``continue`` on that check -- so no ``agent_templates``
row is created for it, and callers compose the orchestrator identity from the
seed dict at read time. On any install seeded by current code there is nothing
to heal, and this migration matches zero rows.

It ships anyway to cover the one case that guard cannot: a row seeded by code
PREDATING the ``SYSTEM_MANAGED_ROLES`` skip. ``ce_0049`` set exactly this
precedent, defensively including "orchestrator" in its default-name list.
``refresh_tenant_template_instructions`` cannot be relied on to reach such a row
either -- it is operator-triggered, never runs on startup, and keys strictly on
byte-equality with the CURRENT seed text, so a legacy row reads as user-edited
and is skipped (the same gap ``ce_0049``/``ce_0084``/``ce_0085`` each healed).

Substring replace, not the old-byte->new-byte swap ``ce_0084``/``ce_0085`` use:
those pinned a single known text generation, but a legacy orchestrator row could
carry any of several older seed generations (BE-9019, BE-9259, BE-9275b). The
two substrings healed here are stable across all of them, so this reaches the
row whichever generation it came from, and leaves the rest of its prose --
including genuine user edits -- untouched.

Both brand residuals a legacy row can hold are healed: the opening heading
(which BE-9275b flipped in code for fresh seeds but never healed in the DB,
having correctly established there were no rows to heal) and the identity
sentence this project flipped. Healing only the second would leave such a row
self-inconsistent -- new sentence under an old heading.

``template_renderer`` tolerates BOTH brand shapes (``_MCP_BOOTSTRAP_MARKER_OLD``
/ ``_ROLE_BOUNDARY_HEADINGS_OLD_NEW``), so a self-hoster who never reruns
migrations still renders correctly. This is a data cleanliness pass, not a
correctness dependency.

Idempotent: each UPDATE is guarded by a LIKE on the OLD substring, and REPLACE is
a no-op once the substring is gone, so the rerun the CE installer performs on
every boot matches zero rows.

Edition Scope: CE -- ``agent_templates`` is a CE table (``migrations/versions/``).
SaaS inherits this migration unchanged via its next ``preDeploy`` alembic run.
"""

import sqlalchemy as sa
from alembic import op


revision = "ce_0090_heal_giljo_hq_orchestrator_identity"
down_revision = "ce_0089_be9348_repair_absorbed_closeout_arguments"
branch_labels = None
depends_on = None

# (old, new) substring pairs. Both are specific enough that a match is our own
# brand text, not a user's coincidental wording.
_REPLACEMENTS: list[tuple[str, str]] = [
    # The identity sentence BE-9361 flipped.
    (
        "You are the **Orchestrator Agent** for **GiljoAI MCP**",
        "You are the **Orchestrator Agent** for **Giljo HQ**",
    ),
    # The opening heading BE-9275b flipped in code but had no row to heal.
    ("# GiljoAI MCP Agent", "# Giljo HQ Agent"),
]


def _apply(pairs: list[tuple[str, str]]) -> None:
    conn = op.get_bind()
    for old, new in pairs:
        conn.execute(
            sa.text(
                "UPDATE agent_templates "  # noqa: S608 -- static SQL, values are bound parameters
                "SET user_instructions = REPLACE(user_instructions, :old, :new) "
                "WHERE user_instructions LIKE :pattern"
            ),
            {"old": old, "new": new, "pattern": f"%{old}%"},
        )


def upgrade() -> None:
    _apply(_REPLACEMENTS)


def downgrade() -> None:
    _apply([(new, old) for old, new in _REPLACEMENTS])
