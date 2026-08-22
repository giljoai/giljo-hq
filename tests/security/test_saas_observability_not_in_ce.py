# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Error-tracking code must not live in CE-shipped guard/gate paths.

Both files below once carried an inline, ``GILJO_MODE == "saas"``-gated Sentry
capture. That shape is invisible to every gate we have — the SaaS import is lazy
so the import-boundary scanner sees nothing, there is no DB access so the
SaaS-table check sees nothing, and the Deletion Test runs at ``GILJO_MODE=""``
so the branch is simply skipped. The capture now lives behind the extension
pattern in ``saas/observability/tripwires.py``.

This test is the standing proof that it stays there: CE announces a neutral
signal and imports nothing to act on it.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]

CE_PATHS_THAT_MUST_NOT_TRACK_ERRORS = (
    "src/giljo_mcp/tenant_guard.py",
    "src/giljo_mcp/signals.py",
    "api/endpoints/mcp_auth_middleware.py",
)


@pytest.mark.parametrize("relative_path", CE_PATHS_THAT_MUST_NOT_TRACK_ERRORS)
def test_ce_guard_path_does_not_reference_sentry(relative_path):
    source = (_REPO_ROOT / relative_path).read_text(encoding="utf-8")
    assert "sentry_sdk" not in source, (
        f"{relative_path} must not reference sentry_sdk — a deployment's error tracking "
        "belongs in saas/observability/tripwires.py, reached via giljo_mcp.signals."
    )


def test_signal_hub_imports_nothing_beyond_the_stdlib():
    """The hub is the CE/deployment seam; a dependency here would defeat the point."""
    source = (_REPO_ROOT / "src/giljo_mcp/signals.py").read_text(encoding="utf-8")
    imports = [line.strip() for line in source.splitlines() if line.startswith(("import ", "from "))]
    assert imports == [
        "from __future__ import annotations",
        "import logging",
        "from collections.abc import Callable",
        "from typing import Any",
    ], f"unexpected imports in signals.py: {imports}"


def test_repeated_registration_does_not_double_announce():
    """Both boot-time registrations can run more than once (import-time safety nets)."""
    from giljo_mcp import signals

    signals.clear_signal_observers()
    try:
        seen = []

        def observer(payload):
            seen.append(payload)

        signals.register_signal_observer("test.signal", observer)
        signals.register_signal_observer("test.signal", observer)
        signals.publish_signal("test.signal", {"x": 1})
        assert seen == [{"x": 1}], "the same observer registered twice must fire once"
    finally:
        signals.clear_signal_observers()


def test_a_failing_observer_does_not_block_the_others_or_the_publisher():
    """Fan-out isolation: publishing is best-effort for the publisher AND per observer."""
    from giljo_mcp import signals

    signals.clear_signal_observers()
    try:
        reached = []

        def boom(_payload):
            raise RuntimeError("observer down")

        def ok(payload):
            reached.append(payload)

        signals.register_signal_observer("test.signal", boom)
        signals.register_signal_observer("test.signal", ok)
        signals.publish_signal("test.signal", {"x": 1})  # must not raise
        assert reached == [{"x": 1}]
    finally:
        signals.clear_signal_observers()
