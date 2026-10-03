# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ast
from pathlib import Path

import pytest

from giljo_mcp.http import url_resolver


def test_no_not_equal_saas_guard():
    tree = ast.parse(Path(url_resolver.__file__).read_text())
    offending = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and any(isinstance(op, ast.NotEq) for op in node.ops)
        and any(isinstance(c, ast.Constant) and c.value in ("saas", "ce") for c in node.comparators)
    ]
    assert offending == [], f"banned != mode guard at line(s) {offending}"


@pytest.mark.parametrize("mode", ["", "ce", "demo"])
def test_the_pin_is_only_read_in_saas_mode(monkeypatch, mode):
    monkeypatch.setenv("GILJO_MODE", mode)
    monkeypatch.setenv("GILJO_PUBLIC_BASE_URL", "https://app.example.test")
    assert url_resolver._saas_pinned_base_url() is None
