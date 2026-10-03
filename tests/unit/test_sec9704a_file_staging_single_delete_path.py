# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.file_staging import FileStaging


def test_there_is_no_unchecked_rmtree_method():
    assert not hasattr(FileStaging, "cleanup"), "cleanup() rmtrees base/tenant/token with no path-escape check"
    assert hasattr(FileStaging, "purge_token_dir")
