# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.taxonomy_service import TaxonomyService


pytestmark = pytest.mark.asyncio


@pytest.fixture
def tenant_a():
    return "tenant_taxonomy_a"


@pytest.fixture
def tenant_b():
    return "tenant_taxonomy_b"


async def _seed_type(service: TaxonomyService, tenant_key: str, abbr: str, label: str):
    return await service.create_type(
        tenant_key=tenant_key,
        abbreviation=abbr,
        label=label,
    )


async def test_list_types_is_tenant_scoped(db_manager, db_session, tenant_a, tenant_b):
    service = TaxonomyService(db_manager=db_manager, session=db_session)

    await _seed_type(service, tenant_a, "AAA", "Alpha")
    await _seed_type(service, tenant_b, "BBB", "Bravo")

    a_rows = await service.list_types(tenant_a)
    b_rows = await service.list_types(tenant_b)

    a_abbrs = {r.abbreviation for r in a_rows}
    b_abbrs = {r.abbreviation for r in b_rows}

    assert "AAA" in a_abbrs
    assert "BBB" not in a_abbrs
    assert "BBB" in b_abbrs
    assert "AAA" not in b_abbrs


async def test_validate_returns_row_when_present(db_manager, db_session, tenant_a):
    service = TaxonomyService(db_manager=db_manager, session=db_session)
    created = await _seed_type(service, tenant_a, "QQQ", "Quebec")

    resolved = await service.validate("QQQ", tenant_a)

    assert resolved.id == created.id
    assert resolved.abbreviation == "QQQ"


async def test_validate_raises_with_valid_types_payload(db_manager, db_session, tenant_a):
    service = TaxonomyService(db_manager=db_manager, session=db_session)
    await _seed_type(service, tenant_a, "RRR", "Romeo")

    with pytest.raises(ValidationError) as excinfo:
        await service.validate("ZZZ", tenant_a)

    err = excinfo.value
    assert "Unknown taxonomy type" in str(err)
    valid_types = err.context.get("valid_types") or []
    abbrs = {t["abbreviation"] for t in valid_types}
    assert "RRR" in abbrs


async def test_validate_does_not_leak_other_tenants_types(db_manager, db_session, tenant_a, tenant_b):
    service = TaxonomyService(db_manager=db_manager, session=db_session)
    await _seed_type(service, tenant_b, "SSS", "Sierra")

    with pytest.raises(ValidationError):
        await service.validate("SSS", tenant_a)


async def test_create_type_same_abbreviation_in_different_tenants(db_manager, db_session, tenant_a, tenant_b):
    service = TaxonomyService(db_manager=db_manager, session=db_session)

    a_row = await _seed_type(service, tenant_a, "TTT", "Tango")
    b_row = await _seed_type(service, tenant_b, "TTT", "Tango")

    assert a_row.id != b_row.id
    assert a_row.tenant_key == tenant_a
    assert b_row.tenant_key == tenant_b
