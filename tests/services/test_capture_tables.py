# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from sqlalchemy import Column, MetaData, String, Table
from sqlalchemy import inspect as sa_inspect

from giljo_mcp.services.capture_tables import (
    EXPORT_EXCLUDE,
    capture_models,
    capture_table_names,
    models_by_table,
    unaccounted_tenant_tables,
)


def test_every_captured_model_is_tenant_keyed_and_not_excluded():
    models = capture_models()
    assert len(models) >= 30, "CE registry alone must discover the core capture set"
    for model in models:
        columns = {c.name for c in sa_inspect(model).columns}
        assert "tenant_key" in columns, f"{model.__name__} captured without tenant_key"
        assert model.__tablename__ not in EXPORT_EXCLUDE, f"{model.__tablename__} is excluded yet captured"


def test_previously_drifted_ce_tables_are_captured():
    captured = set(capture_table_names())
    for table in (
        "comm_threads",
        "comm_participants",
        "roadmaps",
        "roadmap_items",
        "sequence_runs",
        "notifications",
        "tenant_skills_ack",
    ):
        assert table in captured, f"{table} must be discovered in the CE registry"


def test_order_is_topological_and_deterministic():
    order = capture_table_names()
    assert order == capture_table_names(), "two discovery calls must agree"
    pos = {name: i for i, name in enumerate(order)}
    for model in capture_models():
        for fk in model.__table__.foreign_keys:
            parent = fk.column.table.name
            if parent != model.__tablename__ and parent in pos:
                assert pos[parent] < pos[model.__tablename__], f"{parent} must precede {model.__tablename__}"
    purge_pos = {name: i for i, name in enumerate(reversed(order))}
    assert purge_pos["messages"] < purge_pos["comm_threads"] < purge_pos["projects"]


def test_models_by_table_maps_every_captured_table():
    mapping = models_by_table()
    assert set(mapping) == set(capture_table_names())
    assert all(mapping[name].__tablename__ == name for name in mapping)


def test_unaccounted_flags_an_unmapped_tenant_table():
    synthetic = MetaData()
    Table(
        "synthetic_ce_widgets",
        synthetic,
        Column("id", String(36), primary_key=True),
        Column("tenant_key", String(36), nullable=False),
    )
    assert unaccounted_tenant_tables(metadata=synthetic) == {"synthetic_ce_widgets"}
