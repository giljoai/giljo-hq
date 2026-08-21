# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-9417: nothing stands in for an ORM row with a spec'd mock.

INF-9399 measured why. A declarative model declares its columns as CLASS
attributes, so ``MagicMock(spec=Project)`` and ``create_autospec(Project)``
auto-vivify each newly added column as a truthy child mock -- exactly as wrongly
as a bare ``MagicMock``. A real transient instance from
``tests/helpers/model_factories.py`` answers ``None``, because that is what an
unset nullable column is.

That was a convention with nothing checking it, and the population had grown to
32 sites across 10 files by the time it was converted. This guard is the
mechanism half: the convention now drifts loudly instead of quietly.

WHY THIS CANNOT BE A SUBSTRING SCAN, unlike its sibling
``test_inf9422_mcp_session_seam.py``: ``spec=`` is CORRECT for behavioural
collaborators, and the suite has 46 such sites -- ``ToolAccessor``,
``AsyncSession``, ``TenantManager``, ``AsyncClient``, ``DatabaseManager``,
``WebSocketManager``, ``Request``. There a spec does real work: a removed or
renamed METHOD raises ``AttributeError`` where a bare mock would answer
silently, and there is no cheap real object to build instead. A text scan cannot
tell those from ``spec=Project``, so this walks the AST and resolves the spec
target against the live mapper registry.

Import ALIASES are resolved per file, so ``from giljo_mcp.models import Project
as P`` followed by ``MagicMock(spec=P)`` is caught. That is not hypothetical
polish: the first mutation written to prove this guard has teeth used an alias,
and the guard stayed green. Matching the bare name only would have made it
advisory against exactly the shape a mechanical re-introduction takes.

KNOWN LIMIT, stated rather than left to be discovered: the match is still by
NAME. A spec target computed at runtime (``create_autospec(cls)`` in
``tests/helpers/mcp_dispatch.py``) is invisible here, and a test-local class
sharing a model's name would be a false positive. Both were measured when this
was written: one dynamic site, zero name collisions. This is a ratchet against
the convention eroding, not a proof that no such stand-in can exist.

Edition Scope: Both (test-only guard).
"""

from __future__ import annotations

import ast
from pathlib import Path

import giljo_mcp.models  # noqa: F401  -- imported for the side effect: registers every mapper
from giljo_mcp.database import Base


_TESTS_ROOT = Path(__file__).resolve().parent.parent

# The factory module's own contrast tests deliberately assert what a spec'd mock
# does -- `MagicMock(spec=Project).product_id is not None` -- because that
# measurement is the entire justification for the factories existing, and their
# docstring says they are there so "simplify this to create_autospec" cannot be
# done later without a named check going red. Flagging them would delete the
# proof this guard depends on. Nothing else is ever exempt: converting the site
# is always the cheaper fix, and a second exemption makes this guard advisory.
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
    """Every mapped class name, read from the live registry rather than listed.

    A model added next month is covered without editing this file -- the same
    self-maintaining property ``model_factories._build()`` gives its callers.
    """
    return {mapper.class_.__name__ for mapper in Base.registry.mappers}


def _named(node: ast.expr) -> str | None:
    """The dotted tail of a name reference, or None if it is not one."""
    if isinstance(node, ast.Attribute):
        return node.attr
    return getattr(node, "id", None)


def _spec_target(call: ast.Call, aliases: dict[str, str] | None = None) -> str | None:
    """The model name this call spec's a mock against, if it does.

    ``aliases`` is the module's import table. BOTH positions are resolved through
    it -- the mock factory and the spec target -- because either can be renamed on
    import, and each rename alone is enough to hide the site from a bare-name
    match. ``from unittest.mock import Mock as _M`` is as effective an evasion as
    ``from giljo_mcp.models import Project as P``.
    """
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
    """Local name -> imported name, for every import in the module.

    ``from giljo_mcp.models import Project as P`` yields ``{"P": "Project"}``, so a
    spec target of ``P`` resolves to the model it actually names. Un-aliased
    imports map a name to itself, which is harmless.
    """
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
    """A guard nobody has watched fail is decoration.

    This drives the AST walk and the registry lookup over sites shaped exactly
    like the ones INF-9417 converted, without keeping such a site in the tree for
    the guard above to find.
    """
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

    # ...and stays silent on the collaborator sites that are correct as they are.
    for source in (
        "create_autospec(ToolAccessor, instance=True)",
        "AsyncMock(spec=AsyncSession)",
        "MagicMock(spec=['__call__'])",
        "MagicMock()",
    ):
        assert _spec_target(ast.parse(source, mode="eval").body) not in models, source


def test_an_aliased_import_does_not_evade_the_guard():
    """The first mutation written against this guard used an alias and slipped past.

    ``from giljo_mcp.models import AgentTemplate as _AT`` then ``Mock(spec=_AT)``
    is a model stand-in wearing a different name, and a bare-name match calls it
    a collaborator. Resolving the module's own import table closes it.
    """
    module = ast.parse(
        "from giljo_mcp.models import AgentTemplate as _AT\nfrom unittest.mock import Mock as _M\nx = _M(spec=_AT)\n"
    )
    aliases = _alias_map(module)
    assert aliases["_AT"] == "AgentTemplate"

    call = next(n for n in ast.walk(module) if isinstance(n, ast.Call))
    # Both the mock factory (_M) and the model (_AT) are aliased -- either rename
    # alone defeats a bare-name match, so both are resolved.
    assert _spec_target(call) is None, "bare-name matching should NOT see through the aliases"
    assert _spec_target(call, aliases) == "AgentTemplate"
    assert _spec_target(call, aliases) in _model_names()
