# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest

from giljo_mcp.services.chain_conductor_retire import (
    CHAIN_FINISHED_MESSAGE,
    is_chain_conductor_job,
    retire_chain_conductor,
)
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def test_retiring_an_unknown_conductor_is_a_noop(db_session):
    tenant = TenantManager.generate_tenant_key()
    db_session.info["tenant_key"] = tenant

    await retire_chain_conductor(None, TenantManager(), str(uuid4()), tenant, db_session, None)


async def test_an_unknown_job_is_not_a_chain_conductor(db_session):
    tenant = TenantManager.generate_tenant_key()
    db_session.info["tenant_key"] = tenant

    assert await is_chain_conductor_job(db_session, tenant, str(uuid4())) is False


def test_late_reply_is_true_for_finished_and_stopped_chains():
    assert "finished or was stopped" in CHAIN_FINISHED_MESSAGE
