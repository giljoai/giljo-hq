# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from giljo_mcp.download_tokens import TokenManager
from giljo_mcp.exceptions import DatabaseError


class _BrokenSession:
    info: dict = {}

    async def execute(self, stmt):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


@pytest.mark.asyncio
async def test_get_token_info_raises_on_a_database_fault():
    with pytest.raises(DatabaseError):
        await TokenManager(_BrokenSession()).get_token_info(str(uuid4()), "tenant")


@pytest.mark.asyncio
async def test_get_token_info_by_token_raises_on_a_database_fault():
    with pytest.raises(DatabaseError):
        await TokenManager(_BrokenSession()).get_token_info_by_token(str(uuid4()))


def test_validate_token_is_gone():
    assert not hasattr(TokenManager, "validate_token")
