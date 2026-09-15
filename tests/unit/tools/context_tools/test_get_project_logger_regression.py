# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest

from giljo_mcp.tools.context_tools.get_project import get_project


@pytest.mark.asyncio
async def test_get_project_logger_does_not_typeerror() -> None:
    with pytest.raises(ValueError, match="db_manager parameter is required"):
        await get_project(
            project_id="00000000-0000-0000-0000-000000000000",
            tenant_key="tk_test",
            db_manager=None,
        )
