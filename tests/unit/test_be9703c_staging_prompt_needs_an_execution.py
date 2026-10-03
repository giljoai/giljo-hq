# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator


@pytest.mark.asyncio
async def test_orchestrator_job_without_an_execution_is_refused():
    no_rows = MagicMock()
    no_rows.scalars.return_value.first.return_value = None
    db = AsyncMock()
    db.execute = AsyncMock(return_value=no_rows)
    generator = ThinClientPromptGenerator(db, "tk")
    generator._fetch_project = AsyncMock(return_value=SimpleNamespace(id="p1"))
    generator._fetch_product = AsyncMock(return_value=SimpleNamespace(id="prod1"))
    generator._staging_builder = MagicMock()

    with pytest.raises(ResourceNotFoundError):
        await generator.generate_staging_prompt(orchestrator_id="job-1", project_id="p1")
    generator._staging_builder.build_staging_prompt.assert_not_called()
