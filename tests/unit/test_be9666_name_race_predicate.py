# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from giljo_mcp.services.template_write_paths import AGENT_NAME_RACE_ATTEMPTS, is_agent_name_conflict


def _violation(constraint: str) -> IntegrityError:
    return IntegrityError(
        "INSERT INTO agent_templates ...",
        {},
        Exception(f'duplicate key value violates unique constraint "{constraint}"'),
    )


def test_the_agent_name_index_counts_as_a_name_race():
    assert is_agent_name_conflict(_violation("uq_template_tenant_name_version"))


def test_another_constraint_is_not_a_name_race():
    assert not is_agent_name_conflict(_violation("uq_product_template_assignment"))


def test_the_retry_bound_leaves_room_for_more_than_one_rival():
    assert AGENT_NAME_RACE_ATTEMPTS >= 2
