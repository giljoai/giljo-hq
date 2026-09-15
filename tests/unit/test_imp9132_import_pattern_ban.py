# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("src", "api")
BANNED_NAMES = frozenset({"TENANT_SCOPED_MODELS", "TENANT_SCOPED_TABLES"})


def _py_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        files.extend((REPO_ROOT / root).rglob("*.py"))
    return sorted(files)


def _module_scope_nodes(node: ast.AST):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        yield child
        yield from _module_scope_nodes(child)


def _module_level_banned_imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[tuple[int, str]] = []
    for node in _module_scope_nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "giljo_mcp.database":
            for alias in node.names:
                if alias.name in BANNED_NAMES:
                    hits.append((node.lineno, alias.name))
    return hits


def test_no_module_level_live_property_imports():
    offenders: list[str] = []
    for path in _py_files():
        for lineno, name in _module_level_banned_imports(path):
            offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno} imports {name}")
    assert not offenders, (
        "Module-level `from giljo_mcp.database import TENANT_SCOPED_MODELS/TENANT_SCOPED_TABLES` "
        "SNAPSHOTS the pre-SaaS-registration set at import time — these are PEP 562 live "
        "properties (tenant_guard.py:197-204). Import them INSIDE the function that reads "
        "them so the SaaS-widened union is honored. Offenders:\n" + "\n".join(offenders)
    )
