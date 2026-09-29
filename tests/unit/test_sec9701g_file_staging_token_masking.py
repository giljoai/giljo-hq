# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import uuid
from pathlib import Path

import pytest

from giljo_mcp.file_staging import FileStaging


pytestmark = pytest.mark.asyncio


async def test_create_staging_directory_debug_log_masks_the_token(tmp_path: Path, caplog) -> None:
    staging = FileStaging(base_path=tmp_path)
    token = str(uuid.uuid4())

    with caplog.at_level(logging.DEBUG, logger="giljo_mcp.file_staging"):
        await staging.create_staging_directory("tenant-abc", token)

    assert token not in caplog.text
    assert "Created staging directory" in caplog.text


async def test_traversal_attempt_error_log_masks_the_token(tmp_path: Path, caplog) -> None:
    staging = FileStaging(base_path=tmp_path)
    malicious_token = "../../etc/passwd-lookalike-secret-suffix"

    with caplog.at_level(logging.ERROR, logger="giljo_mcp.file_staging"):
        with pytest.raises(ValueError, match="path traversal"):
            await staging.create_staging_directory("tenant-abc", malicious_token)

    assert malicious_token not in caplog.text
    assert "Directory traversal attempt detected in token" in caplog.text
