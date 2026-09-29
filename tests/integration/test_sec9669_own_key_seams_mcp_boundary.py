# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.exceptions import BaseGiljoError
from tests.integration import test_fe9408_identity_provenance_mcp_boundary as _fe9408
from tests.integration.test_fe9408_identity_provenance_mcp_boundary import (
    _error_text,
    _raw_text,
    _seed_orchestrator_job,
    _seed_org_product,
    _seed_project,
)


mcp_client = _fe9408.mcp_client


@pytest.mark.asyncio
async def test_get_context_metadata_does_not_carry_the_tenant_key(mcp_client):
    client, tenant_key, db_session, _db_manager = mcp_client
    product_id, _ = await _seed_org_product(db_session, tenant_key)

    async with client() as session:
        result = await session.call_tool("get_context", {"product_id": product_id, "categories": ["products"]})
        assert result.is_error is False, _error_text(result)
        raw = _raw_text(result)

    assert "products" in raw
    assert tenant_key not in raw


@pytest.mark.asyncio
async def test_staging_identity_block_does_not_carry_the_tenant_key(mcp_client):
    client, tenant_key, db_session, _db_manager = mcp_client
    product_id, _ = await _seed_org_product(db_session, tenant_key)
    project_id = await _seed_project(db_session, tenant_key, product_id, implementation_launched=False)
    job_id = await _seed_orchestrator_job(db_session, tenant_key, project_id)

    async with client() as session:
        result = await session.call_tool("get_staging_instructions", {"job_id": job_id})
        assert result.is_error is False, _error_text(result)
        raw = _raw_text(result)

    assert '"identity"' in raw
    assert tenant_key not in raw


def test_error_str_scrubs_the_tenant_key_value():
    key = "tk_" + "a" * 32
    err = BaseGiljoError("refused", context={"owner": key, "operation": "x"})

    rendered = str(err)

    assert "(Context:" in rendered
    assert key not in rendered
    assert "tk_[redacted]" in rendered
    assert err.context["owner"] == key
