# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-9422: the SDK session helper is reached through one seam, not 77 imports.

``mcp.shared.memory.create_connected_server_and_client_session`` is removed in
MCP SDK 2.0. The suite reaches it through ``tests/helpers/mcp_session_fixture.py``
so that removal costs one file instead of seventy-seven.

Nothing enforces that but this test. A new boundary suite is almost always
written by copying an existing one, and the copies predate the seam -- so the
direct import comes back by hand, silently, and the seam stops being a seam
exactly when the migration needs it.

Edition Scope: Both (test-only guard).
"""

from pathlib import Path


_TESTS_ROOT = Path(__file__).resolve().parent.parent
_SEAM = _TESTS_ROOT / "helpers" / "mcp_session_fixture.py"

# The seam re-exports the helper, and this guard has to name the module it bans;
# neither may flag itself. Nothing else is ever exempt -- a second exemption
# makes the guard advisory, and re-pointing the import is always the cheaper fix.
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
