# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""OAuth refresh tokens: add ``origin_code_hash`` (code->token linkage for reuse revocation).

Revision ID: ce_0082_oauth_refresh_origin_code_hash
Revises: ce_0081_download_tokens_staged_at
Create Date: 2026-07-19

SEC-9227b (M4) -- records which authorization code minted a refresh family, so
that on authorization-code REUSE (RFC 9700 4.5.3 / RFC 6749 4.1.2) the server can
revoke every refresh family previously issued from that code. The value stored is
the sha256 hex digest of the auth code, NEVER the raw code.

Operations
----------
1. Add nullable ``origin_code_hash`` (String(64)) to ``oauth_refresh_tokens``
   (existence-guarded).

Chain routing
-------------
``oauth_refresh_tokens`` is a CE table (``src/giljo_mcp/models/oauth.py``, created
by ce_0020), so this lives in ``migrations/versions/`` (the CE chain), NEVER
``saas_versions/``. Paired with a parity edit to ``baseline_v38_unified.py``
declaring the same column LAST in the oauth_refresh_tokens create_table -- this
migration appends it, so declaring it last in the baseline keeps the fresh-install
and chain-replay schemas byte-identical (the INF-5060 parity invariant covers
column ORDER). Precedent: ce_0079, ce_0081.

Idempotency
-----------
The column add is guarded by an ``inspect()`` column-existence check. The CE
installer reruns the chain on every boot, so every step must be re-runnable.

Data-facing DoD
---------------
Additive only: one nullable column, no default, NO BACKFILL. Tolerance rather
than data surgery (rule (a)) -- refresh families minted before this upgrade keep
``origin_code_hash IS NULL`` and simply cannot be retro-linked to their code for
reuse revocation; that residual is acceptable (a stolen pre-migration code whose
family predates this column can still be rejected, just not family-revoked). No
existing row is invalidated.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "ce_0082_oauth_refresh_origin_code_hash"
down_revision = "ce_0081_download_tokens_staged_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("oauth_refresh_tokens")]

    if "origin_code_hash" not in columns:
        op.add_column(
            "oauth_refresh_tokens",
            sa.Column(
                "origin_code_hash",
                sa.String(length=64),
                nullable=True,
                comment="SEC-9227b: sha256 hex of the auth code that minted this family; enables reuse-revocation",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("oauth_refresh_tokens")]

    if "origin_code_hash" in columns:
        op.drop_column("oauth_refresh_tokens", "origin_code_hash")
