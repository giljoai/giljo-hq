# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "ce_0079_users_tutorial_reentry_state"
down_revision = "ce_0078_projects_superseded_status_and_successor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("users")]

    if "learning_beat" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "learning_beat",
                sa.Integer(),
                nullable=True,
                comment="BE-9201: last onboarding-tutorial beat reached (1-6); NULL until the tutorial persists it",
            ),
        )

    if "router_choice" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "router_choice",
                sa.String(length=8),
                nullable=True,
                comment="BE-9201: tutorial router door picked (A|B|C|D); drives the bootstrap-card spotlight",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("users")]

    if "router_choice" in columns:
        op.drop_column("users", "router_choice")
    if "learning_beat" in columns:
        op.drop_column("users", "learning_beat")
