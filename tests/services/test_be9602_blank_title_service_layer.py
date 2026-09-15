# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("title", ["", "   ", "\n\t"])
async def test_task_service_create_task_refuses_blank_title(two_tenant_service_setup, title):
    setup = two_tenant_service_setup
    with pytest.raises(ValidationError):
        await setup["task_service_a"].create_task(
            title=title,
            description="body",
            product_id=setup["product_a"].id,
            tenant_key=setup["tenant_a"],
        )


async def test_task_service_update_task_refuses_whitespace_title(two_tenant_service_setup, db_session):
    setup = two_tenant_service_setup
    task_id = await setup["task_service_a"].create_task(
        title="real title",
        description="body",
        product_id=setup["product_a"].id,
        tenant_key=setup["tenant_a"],
    )
    TenantManager.set_current_tenant(setup["tenant_a"])
    try:
        with pytest.raises(ValidationError):
            await setup["task_service_a"].update_task(task_id, title="   ")
    finally:
        TenantManager.clear_current_tenant()


@pytest.mark.parametrize("name", ["", "   "])
async def test_project_service_create_project_refuses_blank_name(two_tenant_service_setup, name):
    setup = two_tenant_service_setup
    with pytest.raises(ValidationError):
        await setup["project_service_a"].create_project(
            name=name,
            mission="m",
            description="d",
            product_id=setup["product_a"].id,
            tenant_key=setup["tenant_a"],
        )


async def test_project_service_update_project_refuses_whitespace_name(two_tenant_service_setup):
    setup = two_tenant_service_setup
    TenantManager.set_current_tenant(setup["tenant_a"])
    try:
        with pytest.raises(ValidationError):
            await setup["project_service_a"].update_project(setup["project_a"].id, {"name": "  "})
    finally:
        TenantManager.clear_current_tenant()
