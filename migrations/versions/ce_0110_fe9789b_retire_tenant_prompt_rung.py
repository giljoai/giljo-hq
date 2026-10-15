# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

import sqlalchemy as sa
from alembic import op


revision = "ce_0110_fe9789b_retire_tenant_prompt_rung"
down_revision = "ce_0109_be9755_template_proposals"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_TENANT_KEY = "system.orchestrator_prompt"
_PROPOSALS = "template_proposals"


def _non_empty(value: str) -> str:
    return (
        f"(CASE WHEN {value}->>'mode' = 'additions' "
        f"THEN COALESCE({value}->>'additions', '') <> '' "
        f"ELSE COALESCE({value}->>'content', '') <> '' END)"
    )


_COPY_TO_PRODUCTS = f"""
INSERT INTO configurations
    (id, tenant_key, project_id, key, value, category, description, created_at, updated_at)
SELECT gen_random_uuid()::text, t.tenant_key, NULL, :prefix || ':' || lower(p.id), t.value,
       'system', 'Administrator override for orchestrator prompt (product-scoped)',
       now(), COALESCE(t.updated_at, t.created_at, now())
FROM configurations t
JOIN products p ON p.tenant_key = t.tenant_key AND p.deleted_at IS NULL
WHERE t.key = :prefix AND t.tenant_key IS NOT NULL AND {_non_empty("t.value")}
ON CONFLICT ON CONSTRAINT uq_config_tenant_key DO UPDATE
    SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
    WHERE NOT {_non_empty("configurations.value")}
"""

_DELETE_TENANT_ROWS = "DELETE FROM configurations WHERE key = :prefix AND tenant_key IS NOT NULL"

_DELETE_TENANT_PROPOSALS = (
    "DELETE FROM template_proposals WHERE target_kind = 'orchestrator_additions' AND rung = 'tenant'"
)


def upgrade() -> None:
    conn = op.get_bind()
    params = {"prefix": _TENANT_KEY}
    copied = conn.execute(sa.text(_COPY_TO_PRODUCTS), params).rowcount
    dropped = conn.execute(sa.text(_DELETE_TENANT_ROWS), params).rowcount
    discarded = 0
    if sa.inspect(conn).has_table(_PROPOSALS):
        discarded = conn.execute(sa.text(_DELETE_TENANT_PROPOSALS)).rowcount
    logger.info(
        "ce_0110: copied the account-wide orchestrator prompt onto %d product rows, removed %d account-wide rows, "
        "discarded %d waiting account-wide proposals",
        copied,
        dropped,
        discarded,
    )


def downgrade() -> None:
    logger.warning(
        "ce_0110 downgrade is a no-op: the per-product orchestrator prompts stay as they are "
        "and the account-wide rows are not recreated."
    )
