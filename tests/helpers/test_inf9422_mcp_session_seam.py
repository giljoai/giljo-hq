# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from pathlib import Path


_TESTS_ROOT = Path(__file__).resolve().parent.parent
_SEAM = _TESTS_ROOT / "helpers" / "mcp_session_fixture.py"

_ALLOWED = {_SEAM, Path(__file__).resolve()}

_SDK_MODULE = "mcp.shared.memory"


def _test_tree_python_files():
    for path in sorted(_TESTS_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def test_only_the_seam_reaches_the_sdk_session_module():
    offenders = [
        path.relative_to(_TESTS_ROOT).as_posix()
        for path in _test_tree_python_files()
        if path not in _ALLOWED and _SDK_MODULE in path.read_text(encoding="utf-8")
    ]

    assert not offenders, (
        f"{len(offenders)} test file(s) reach {_SDK_MODULE} directly. That module's "
        "create_connected_server_and_client_session is removed in MCP SDK 2.0 -- import it "
        f"from tests.helpers.mcp_session_fixture instead. Offenders: {offenders}"
    )


def test_the_seam_exports_a_usable_session_helper():
    from tests.helpers import mcp_session_fixture

    assert mcp_session_fixture.__all__ == ["create_connected_server_and_client_session"]
    assert callable(mcp_session_fixture.create_connected_server_and_client_session)
