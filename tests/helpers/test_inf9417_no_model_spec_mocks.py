# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ast
from pathlib import Path

import giljo_mcp.models  # noqa: F401  -- imported for the side effect: registers every mapper
from giljo_mcp.database import Base


_TESTS_ROOT = Path(__file__).resolve().parent.parent

_ALLOWED = {
    _TESTS_ROOT / "helpers" / "test_inf9399_model_factory_shape.py",
    Path(__file__).resolve(),
}

_MOCK_FACTORIES = {
    "Mock",
    "MagicMock",
    "AsyncMock",
    "NonCallableMock",
    "NonCallableMagicMock",
}


def _model_names() -> set[str]:
    return {mapper.class_.__name__ for mapper in Base.registry.mappers}


def _named(node: ast.expr) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    return getattr(node, "id", None)


def _spec_target(call: ast.Call, aliases: dict[str, str] | None = None) -> str | None:
    aliases = aliases or {}

    def resolve(node: ast.expr) -> str | None:
        name = _named(node)
        return aliases.get(name, name)

    func = resolve(call.func)
    if func == "create_autospec":
        if call.args:
            return resolve(call.args[0])
        return next((resolve(kw.value) for kw in call.keywords if kw.arg == "spec"), None)
    if func in _MOCK_FACTORIES:
        for keyword in call.keywords:
            if keyword.arg in {"spec", "spec_set"}:
                return resolve(keyword.value)
    return None


def _alias_map(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                imported = alias.name.rsplit(".", 1)[-1]
                aliases[alias.asname or imported] = imported
    return aliases


def _test_tree_python_files():
    for path in sorted(_TESTS_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts or path in _ALLOWED:
            continue
        yield path


def test_no_declarative_model_is_stood_in_for_by_a_specd_mock():
    models = _model_names()
    offenders: list[str] = []

    for path in _test_tree_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = _alias_map(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = _spec_target(node, aliases)
            if target in models:
                offenders.append(f"{path.relative_to(_TESTS_ROOT).as_posix()}:{node.lineno} ({target})")

    assert not offenders, (
        f"{len(offenders)} site(s) stand in for an ORM row with a spec'd mock. A spec "
        "constrains WHICH attributes exist, not what they answer -- a declarative model "
        "declares its columns as class attributes, so every column added after such a test "
        "was written auto-vivifies as a TRUTHY child mock, and production code branching on "
        "`if row.some_nullable_column:` takes the wrong branch silently. Build a real "
        "transient instance instead: tests/helpers/model_factories.py (make_project / "
        "make_product / make_agent_template / make_agent_execution / "
        "make_product_memory_entry / make_vision_document), which answers None for an unset "
        "nullable column because that is what one is. `spec=` stays correct for behavioural "
        f"collaborators (services, ToolAccessor, sessions). Offenders: {offenders}"
    )


def test_the_guard_can_actually_see_an_offender():
    models = _model_names()
    assert "Project" in models, "the mapper registry did not load; the guard would pass vacuously"

    for source in (
        "MagicMock(spec=Project)",
        "Mock(spec=Project)",
        "AsyncMock(spec_set=Project)",
        "create_autospec(Project)",
        "create_autospec(spec=Project)",
        "mock.MagicMock(spec=models.Project)",
    ):
        assert _spec_target(ast.parse(source, mode="eval").body) == "Project", source

    for source in (
        "create_autospec(ToolAccessor, instance=True)",
        "AsyncMock(spec=AsyncSession)",
        "MagicMock(spec=['__call__'])",
        "MagicMock()",
    ):
        assert _spec_target(ast.parse(source, mode="eval").body) not in models, source


def test_an_aliased_import_does_not_evade_the_guard():
    module = ast.parse(
        "from giljo_mcp.models import AgentTemplate as _AT\nfrom unittest.mock import Mock as _M\nx = _M(spec=_AT)\n"
    )
    aliases = _alias_map(module)
    assert aliases["_AT"] == "AgentTemplate"

    call = next(n for n in ast.walk(module) if isinstance(n, ast.Call))
    assert _spec_target(call) is None, "bare-name matching should NOT see through the aliases"
    assert _spec_target(call, aliases) == "AgentTemplate"
    assert _spec_target(call, aliases) in _model_names()
