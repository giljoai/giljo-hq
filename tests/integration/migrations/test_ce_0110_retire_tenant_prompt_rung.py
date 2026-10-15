# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from giljo_mcp.system_prompts.service import DEFAULT_ORCHESTRATOR_CONFIG_KEY, product_orchestrator_config_key
from tests.integration.migrations.test_ce_0088_completed_at_backfill import (
    _drop_all_objects,
    _run_alembic,
    scratch_engine,  # noqa: F401  (fixture)
)


_PRE = "ce_0109_be9755_template_proposals"
_REV = "ce_0110_fe9789b_retire_tenant_prompt_rung"

TK_A, TK_B, TK_C, TK_D = "tk_ce0110_a", "tk_ce0110_b", "tk_ce0110_c", "tk_ce0110_d"
A_LIVE = "a0000000-0000-4000-8000-000000000001"
A_OWN = "a0000000-0000-4000-8000-000000000002"
A_DELETED = "a0000000-0000-4000-8000-000000000003"
A_EMPTY_OWN = "a0000000-0000-4000-8000-000000000004"
B_OWN = "b0000000-0000-4000-8000-000000000001"
B_NONE = "b0000000-0000-4000-8000-000000000002"
C_LIVE = "c0000000-0000-4000-8000-000000000001"
D_LIVE = "d0000000-0000-4000-8000-000000000001"

A_TENANT_VALUE = {
    "mode": "additions",
    "additions": "A-wide additions",
    "updated_by": "alice@example.test",
    "updated_at": "2026-09-01T10:00:00+00:00",
}
OWN_VALUE = {
    "mode": "additions",
    "additions": "A-OWN product text",
    "updated_by": "bob",
    "updated_at": "2026-10-01T00:00:00+00:00",
}
EMPTY_OWN_VALUE = {"mode": "additions", "additions": "", "updated_by": "bob", "updated_at": "2026-10-01T00:00:00+00:00"}
B_OWN_VALUE = {
    "mode": "additions",
    "additions": "B-OWN",
    "updated_by": "carol",
    "updated_at": "2026-10-02T00:00:00+00:00",
}
C_TENANT_VALUE = {
    "content": "C legacy full replacement",
    "updated_by": "dave",
    "updated_at": "2026-08-01T00:00:00+00:00",
}
D_EMPTY_TENANT_VALUE = {"mode": "additions", "additions": "", "updated_by": "erin"}


@pytest.fixture
def scratch_at_pre(scratch_engine: sa.Engine):  # noqa: F811
    _drop_all_objects(scratch_engine)
    up = _run_alembic("upgrade", _PRE)
    assert up.returncode == 0, f"upgrade to {_PRE} failed:\n{up.stdout}\n{up.stderr}"
    _seed(scratch_engine)
    yield scratch_engine
    _drop_all_objects(scratch_engine)


def _config(conn, tenant_key: str, key: str, value: dict) -> None:
    conn.execute(
        text(
            "INSERT INTO configurations (id, tenant_key, key, value, category, created_at, updated_at) "
            "VALUES (gen_random_uuid()::text, :tk, :key, CAST(:v AS jsonb), 'system', now(), now())"
        ),
        {"tk": tenant_key, "key": key, "v": json.dumps(value)},
    )


def _product(conn, product_id: str, tenant_key: str, *, deleted: bool = False) -> None:
    conn.execute(
        text(
            "INSERT INTO products (id, name, description, tenant_key, is_active, created_at, updated_at, deleted_at) "
            "VALUES (:id, :id, 'ce_0110', :tk, true, now(), now(), CASE WHEN :deleted THEN now() END)"
        ),
        {"id": product_id, "tk": tenant_key, "deleted": deleted},
    )


def _proposal(conn, proposal_id: str, slot_key: str, kind: str, rung: str | None, product_id: str | None) -> None:
    conn.execute(
        text(
            "INSERT INTO template_proposals (id, tenant_key, target_kind, slot_key, product_id, rung, proposed_text, "
            "reason) VALUES (:id, :tk, :kind, :slot, :pid, :rung, 'text', 'why')"
        ),
        {"id": proposal_id, "tk": TK_A, "kind": kind, "slot": slot_key, "pid": product_id, "rung": rung},
    )


def _seed(engine: sa.Engine) -> None:
    with engine.begin() as conn:
        _product(conn, A_LIVE, TK_A)
        _product(conn, A_OWN, TK_A)
        _product(conn, A_DELETED, TK_A, deleted=True)
        _product(conn, A_EMPTY_OWN, TK_A)
        _product(conn, B_OWN, TK_B)
        _product(conn, B_NONE, TK_B)
        _product(conn, C_LIVE, TK_C)
        _product(conn, D_LIVE, TK_D)
        _config(conn, TK_A, DEFAULT_ORCHESTRATOR_CONFIG_KEY, A_TENANT_VALUE)
        _config(conn, TK_A, product_orchestrator_config_key(A_OWN), OWN_VALUE)
        _config(conn, TK_A, product_orchestrator_config_key(A_EMPTY_OWN), EMPTY_OWN_VALUE)
        _config(conn, TK_B, product_orchestrator_config_key(B_OWN), B_OWN_VALUE)
        _config(conn, TK_C, DEFAULT_ORCHESTRATOR_CONFIG_KEY, C_TENANT_VALUE)
        _config(conn, TK_D, DEFAULT_ORCHESTRATOR_CONFIG_KEY, D_EMPTY_TENANT_VALUE)
        _proposal(conn, "prop-tenant", "orchestrator_additions:tenant", "orchestrator_additions", "tenant", None)
        _proposal(
            conn,
            "prop-product",
            f"orchestrator_additions:product:{A_LIVE}",
            "orchestrator_additions",
            "product",
            A_LIVE,
        )
        _proposal(conn, "prop-template", "agent_template:t1", "agent_template", None, None)


def _rows(engine: sa.Engine) -> dict[tuple[str, str], dict]:
    with engine.connect() as conn:
        found = conn.execute(
            text("SELECT tenant_key, key, value FROM configurations WHERE key LIKE 'system.orchestrator_prompt%'")
        ).all()
    return {(tk, key): value for tk, key, value in found}


def _proposal_ids(engine: sa.Engine) -> set[str]:
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(text("SELECT id FROM template_proposals"))}


def _upgrade() -> None:
    up = _run_alembic("upgrade", _REV)
    assert up.returncode == 0, f"upgrade {_REV} failed:\n{up.stdout}\n{up.stderr}"


@pytest.mark.integration
class TestCe0110RetireTenantPromptRung:
    def test_each_live_product_inherits_the_account_wide_row_byte_for_byte(self, scratch_at_pre: sa.Engine) -> None:
        _upgrade()
        rows = _rows(scratch_at_pre)

        assert rows[(TK_A, product_orchestrator_config_key(A_LIVE))] == A_TENANT_VALUE
        assert rows[(TK_C, product_orchestrator_config_key(C_LIVE))] == C_TENANT_VALUE

    def test_a_products_own_non_empty_row_is_never_overwritten(self, scratch_at_pre: sa.Engine) -> None:
        _upgrade()
        rows = _rows(scratch_at_pre)

        assert rows[(TK_A, product_orchestrator_config_key(A_OWN))] == OWN_VALUE
        assert rows[(TK_B, product_orchestrator_config_key(B_OWN))] == B_OWN_VALUE

    def test_an_empty_own_row_was_falling_through_so_it_takes_the_inherited_value(
        self, scratch_at_pre: sa.Engine
    ) -> None:
        _upgrade()

        assert _rows(scratch_at_pre)[(TK_A, product_orchestrator_config_key(A_EMPTY_OWN))] == A_TENANT_VALUE

    def test_a_soft_deleted_product_and_another_tenants_products_get_nothing(self, scratch_at_pre: sa.Engine) -> None:
        _upgrade()
        rows = _rows(scratch_at_pre)

        assert (TK_A, product_orchestrator_config_key(A_DELETED)) not in rows
        assert (TK_B, product_orchestrator_config_key(B_NONE)) not in rows
        assert not any(tk == TK_B and value == A_TENANT_VALUE for (tk, _), value in rows.items())
        assert (TK_D, product_orchestrator_config_key(D_LIVE)) not in rows

    def test_every_account_wide_row_is_gone(self, scratch_at_pre: sa.Engine) -> None:
        _upgrade()

        assert not [key for (_, key) in _rows(scratch_at_pre) if key == DEFAULT_ORCHESTRATOR_CONFIG_KEY]

    def test_waiting_account_wide_proposals_are_discarded_and_the_rest_stay(self, scratch_at_pre: sa.Engine) -> None:
        _upgrade()

        assert _proposal_ids(scratch_at_pre) == {"prop-product", "prop-template"}

    def test_a_rerun_changes_nothing_and_never_overwrites_what_a_person_saved(self, scratch_at_pre: sa.Engine) -> None:
        _upgrade()
        edited = {**A_TENANT_VALUE, "additions": "edited after the migration"}
        with scratch_at_pre.begin() as conn:
            conn.execute(
                text("UPDATE configurations SET value = CAST(:v AS jsonb) WHERE tenant_key = :tk AND key = :key"),
                {"v": json.dumps(edited), "tk": TK_A, "key": product_orchestrator_config_key(A_LIVE)},
            )
            _config(
                conn, TK_A, DEFAULT_ORCHESTRATOR_CONFIG_KEY, {**A_TENANT_VALUE, "additions": "a late old-code save"}
            )
        after_first = _rows(scratch_at_pre)

        assert _run_alembic("stamp", _PRE).returncode == 0
        _upgrade()
        after_rerun = _rows(scratch_at_pre)

        assert after_rerun[(TK_A, product_orchestrator_config_key(A_LIVE))] == edited
        assert after_rerun[(TK_A, product_orchestrator_config_key(A_OWN))] == OWN_VALUE
        assert {k: v for k, v in after_rerun.items() if k[1] != DEFAULT_ORCHESTRATOR_CONFIG_KEY} == {
            k: v for k, v in after_first.items() if k[1] != DEFAULT_ORCHESTRATOR_CONFIG_KEY
        }
        assert (TK_A, DEFAULT_ORCHESTRATOR_CONFIG_KEY) not in after_rerun

    def test_downgrade_is_a_no_op_that_keeps_the_product_rows(self, scratch_at_pre: sa.Engine) -> None:
        _upgrade()
        before = _rows(scratch_at_pre)

        down = _run_alembic("downgrade", _PRE)
        assert down.returncode == 0, f"downgrade failed:\n{down.stdout}\n{down.stderr}"

        assert _rows(scratch_at_pre) == before
