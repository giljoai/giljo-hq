# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from contextlib import asynccontextmanager

import pytest

from giljo_mcp.models import Project
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.tools.context_tools.fetch_context import fetch_context


pytestmark = pytest.mark.asyncio


class _SessionYieldingDBManager:
    def __init__(self, session, tenant_key: str):
        self._session = session
        self._tenant_key = tenant_key

    def get_session_async(self, *_args, **_kwargs):
        session = self._session
        session.info["tenant_key"] = self._tenant_key

        @asynccontextmanager
        async def _cm():
            yield session

        return _cm()


async def test_project_payload_carries_taxonomy_alias_alongside_project_alias(db_session, test_tenant_key):
    product = Product(
        id=str(uuid.uuid4()),
        name="BE-9602 Product",
        description="alias payload test",
        tenant_key=test_tenant_key,
        is_active=True,
        product_memory={},
    )
    db_session.add(product)
    ptype = TaxonomyType(id=str(uuid.uuid4()), tenant_key=test_tenant_key, abbreviation="BE", label="Backend")
    db_session.add(ptype)
    await db_session.flush()
    project = Project(
        id=str(uuid.uuid4()),
        name="BE-9602 Project",
        description="alias payload test",
        mission="m",
        tenant_key=test_tenant_key,
        product_id=product.id,
        project_type_id=ptype.id,
        status="inactive",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()

    response = await fetch_context(
        product_id=str(product.id),
        tenant_key=test_tenant_key,
        project_id=project.id,
        categories=["project"],
        db_manager=_SessionYieldingDBManager(db_session, test_tenant_key),
    )

    data = response["data"]["project"]
    assert data["project_alias"] == project.alias
    assert data["taxonomy_alias"] == f"BE-{project.series_number:04d}"
