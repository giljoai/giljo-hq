# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import subprocess
import sys
import textwrap


def test_chunker_gets_encoding_offline_without_cache_dir(tmp_path):
    code = textwrap.dedent(
        """
        from giljo_mcp.context_management.chunker import VisionDocumentChunker
        assert VisionDocumentChunker().encoding.encode("hello world")
        """
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HOME": str(tmp_path),
        "DATA_GYM_CACHE_DIR": str(tmp_path / "empty-cache"),
    }
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stderr[-800:]
