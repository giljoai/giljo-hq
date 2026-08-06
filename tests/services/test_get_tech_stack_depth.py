# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-9322 DoD item 3: prove the get_tech_stack depth control produces a genuine
field-level output difference against real product rows.

A black-box QA harness (Suite A, 2026-07-31) measured that
``get_context(categories=['tech_stack'])`` returned byte-identical output for
'required' vs 'all' (154 chars both) -- the setting was settable and
persisted to the DB but had no consumer.

(The companion ``depth_architecture`` control was found dead by the same
harness but is deliberately held unwired -- its stored default is "overview",
and honoring it would silently shrink every existing user's context. Not
covered by this file; see fetch_context.py's ``_fetch_category``.)

These tests seed a real Product + ProductTechStack row and call the tool
directly with each depth value, asserting a genuine SUBSET relationship:
every key 'required' returns is present in 'all' with the identical value,
AND at least one key is present in the larger response that is absent from
the smaller one. An assertion that only checked "the two strings differ"
would pass for a broken implementation that scrambled a single character;
this checks the actual field sets.

Uses ``db_session.commit()`` + the tool's optional ``session=`` injection
point (the same test-session-injection pattern documented on
``get_tasks()``) so the seeded rows are visible within the same transaction
-- a separate ``db_manager.get_session_async()`` connection cannot see an
uncommitted savepoint from a sibling connection.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from giljo_mcp.models.products import Product, ProductTechStack
from giljo_mcp.tools.context_tools.get_tech_stack import get_tech_stack
from tests.fixtures.base_fixtures import TestData


pytestmark = pytest.mark.asyncio


def _add_product(session, tenant_key: str) -> Product:
    product = Product(
        id=str(uuid.uuid4()),
        name="Depth Test Product",
        description="BE-9322 fixture",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(product)
    return product


async def test_tech_stack_required_is_a_genuine_subset_of_all(db_session):
    tenant_key = TestData.generate_tenant_key()
    product = _add_product(db_session, tenant_key)
    await db_session.flush()

    db_session.add(
        ProductTechStack(
            product_id=product.id,
            tenant_key=tenant_key,
            programming_languages="Python",
            frontend_frameworks="Vue",
            backend_frameworks="FastAPI",
            databases_storage="PostgreSQL",
            infrastructure="Railway",
            dev_tools="pytest",
            target_windows=True,
            target_linux=True,
            target_macos=False,
            target_android=False,
            target_ios=False,
            target_cross_platform=False,
        )
    )
    await db_session.commit()

    required = await get_tech_stack(
        product_id=product.id, tenant_key=tenant_key, sections="required", session=db_session
    )
    everything = await get_tech_stack(product_id=product.id, tenant_key=tenant_key, sections="all", session=db_session)

    required_data = required["data"]
    all_data = everything["data"]

    # The bug this guards: before the fix these two dicts were byte-identical.
    assert required_data != all_data, "'required' and 'all' must not be byte-identical (BE-9322 regression)"

    # Genuine SUBSET: every key+value in 'required' also appears, unchanged, in 'all'.
    for key, value in required_data.items():
        assert key in all_data, f"'required' key {key!r} missing from 'all' -- not a subset"
        assert all_data[key] == value, f"'required'.{key}={value!r} != 'all'.{key}={all_data[key]!r}"

    # At least one key exists in 'all' that 'required' genuinely omits.
    dropped_keys = set(all_data) - set(required_data)
    assert dropped_keys, "'all' must contain at least one field 'required' omits"
    assert dropped_keys <= {
        "target_windows",
        "target_linux",
        "target_macos",
        "target_android",
        "target_ios",
        "target_cross_platform",
    }
    # Spot-check the core fields are untouched by the sections setting.
    assert required_data["programming_languages"] == "Python"
    assert required_data["target_platforms"] == all_data["target_platforms"]


async def test_tech_stack_unrecognized_sections_value_falls_back_to_all(db_session):
    """Tolerance for legacy/unexpected stored values: only exactly 'required'
    narrows the fields; anything else (including a value not in the enum,
    which cannot happen through the validated API but could exist in an old
    row) must behave like 'all' -- never crash, never silently drop core data."""
    tenant_key = TestData.generate_tenant_key()
    product = _add_product(db_session, tenant_key)
    await db_session.flush()
    db_session.add(
        ProductTechStack(
            product_id=product.id,
            tenant_key=tenant_key,
            programming_languages="Go",
            target_windows=True,
        )
    )
    await db_session.commit()

    legacy_value = await get_tech_stack(
        product_id=product.id, tenant_key=tenant_key, sections="some_unrecognized_value", session=db_session
    )
    everything = await get_tech_stack(product_id=product.id, tenant_key=tenant_key, sections="all", session=db_session)

    assert legacy_value["data"] == everything["data"]
