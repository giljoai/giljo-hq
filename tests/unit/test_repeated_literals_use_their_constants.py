# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ast
from pathlib import Path

import pytest

from giljo_mcp.harness_resolver import HARNESS_CLAUDE_CODE
from giljo_mcp.services.next_action import STAGING_COMPLETE
from giljo_mcp.services.protocol_sections.chapters_chain import _CH_BORDER


_REPO = Path(__file__).resolve().parents[2]

_LITERALS = {
    STAGING_COMPLETE: ("STAGING_COMPLETE", "src/giljo_mcp/services/next_action.py"),
    HARNESS_CLAUDE_CODE: ("HARNESS_CLAUDE_CODE", "src/giljo_mcp/harness_resolver.py"),
    _CH_BORDER: ("_CH_BORDER", "src/giljo_mcp/services/protocol_sections/chapters_chain.py"),
}


def _bare_uses(literal: str, constant: str, home: str) -> list[str]:
    found = []
    for root in ("src", "api"):
        for path in (_REPO / root).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if literal not in source:
                continue
            tree = ast.parse(source)
            parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            rel = path.relative_to(_REPO).as_posix()
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Constant) and node.value == literal):
                    continue
                parent = parents[node]
                if isinstance(parent, ast.Dict) and node in parent.keys:
                    continue
                if rel == home and isinstance(parent, ast.Assign) and parent.targets[0].id == constant:
                    continue
                found.append(f"{rel}:{node.lineno}")
    return found


@pytest.mark.parametrize("literal", list(_LITERALS), ids=[name for name, _ in _LITERALS.values()])
def test_literal_is_written_through_its_constant(literal: str) -> None:
    constant, home = _LITERALS[literal]
    assert _bare_uses(literal, constant, home) == [], f"use {constant} from {home}"
