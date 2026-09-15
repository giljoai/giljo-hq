# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ast
from pathlib import Path


_TESTS_ROOT = Path(__file__).resolve().parent.parent

_ALLOWED = {
    _TESTS_ROOT / "conftest.py",
    _TESTS_ROOT / "saas" / "test_alembic_dual_chain.py",
    Path(__file__).resolve(),
}

_MUTATING_METHODS = {
    "setdefault",
    "pop",
    "popitem",
    "update",
    "clear",
    "__setitem__",
    "__delitem__",
}

_MUTATING_OS_FUNCTIONS = {"putenv", "unsetenv"}


def _alias_map(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                imported = alias.name.rsplit(".", 1)[-1]
                aliases[alias.asname or imported] = imported
    return aliases


def _is_os_environ(node: ast.expr, aliases: dict[str, str]) -> bool:
    if isinstance(node, ast.Attribute) and node.attr == "environ":
        base = getattr(node.value, "id", None)
        return base is not None and aliases.get(base, base) == "os"
    name = getattr(node, "id", None)
    return name is not None and aliases.get(name) == "environ"


def _is_os_function(node: ast.expr, aliases: dict[str, str], names: set[str]) -> bool:
    if isinstance(node, ast.Attribute) and node.attr in names:
        base = getattr(node.value, "id", None)
        return base is not None and aliases.get(base, base) == "os"
    name = getattr(node, "id", None)
    return name is not None and aliases.get(name) in names


def env_mutations(tree: ast.Module, aliases: dict[str, str] | None = None) -> list[tuple[int, str]]:
    aliases = {} if aliases is None else aliases
    found: list[tuple[int, str]] = []

    def flag(node: ast.AST, what: str) -> None:
        found.append((getattr(node, "lineno", 0), what))

    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        elif isinstance(node, ast.Delete):
            targets = list(node.targets)

        for target in targets:
            if isinstance(target, ast.Subscript) and _is_os_environ(target.value, aliases):
                verb = "del os.environ[...]" if isinstance(node, ast.Delete) else "os.environ[...] = ..."
                flag(node, verb)

        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in _MUTATING_METHODS
                and _is_os_environ(func.value, aliases)
            ):
                flag(node, f"os.environ.{func.attr}(...)")
            elif _is_os_function(func, aliases, _MUTATING_OS_FUNCTIONS):
                attr = func.attr if isinstance(func, ast.Attribute) else func.id
                flag(node, f"os.{attr}(...)")

    return sorted(set(found))


def _test_tree_python_files():
    for path in sorted(_TESTS_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts or path.resolve() in _ALLOWED:
            continue
        yield path


def test_no_test_mutates_os_environ_directly():
    offenders: list[str] = []

    for path in _test_tree_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = _alias_map(tree)
        for lineno, what in env_mutations(tree, aliases):
            offenders.append(f"{path.relative_to(_TESTS_ROOT).as_posix()}:{lineno}  {what}")

    assert not offenders, (
        f"{len(offenders)} site(s) mutate the process environment directly. os.environ is "
        "PROCESS-GLOBAL and pytest-xdist runs each worker as one long-lived process, so the "
        "value outlives your test and reaches whichever tests the scheduler happens to run "
        "next on that worker -- an order-dependent failure against a test that did not cause "
        "it. Use `monkeypatch.setenv` / `monkeypatch.delenv(..., raising=False)`, which undo "
        "themselves at teardown, or a fixture with `yield` + cleanup. `monkeypatch.setenv` is "
        "also STRONGER than `setdefault`, which silently leaves a value another test leaked "
        "and so asserts against a precondition that may not hold. READING is fine: "
        "`os.environ.get(...)` and `os.environ['X']` in an assertion are untouched. The one "
        f"exemption is tests/conftest.py's import-time bootstrap. Offenders: {offenders}"
    )




def test_the_guard_sees_the_plain_shapes():
    for source, expected in (
        ('import os\nos.environ["JWT_SECRET"] = "x"\n', "os.environ[...] = ..."),
        ('import os\nos.environ.setdefault("JWT_SECRET", "x")\n', "os.environ.setdefault(...)"),
        ('import os\nos.environ.pop("X", None)\n', "os.environ.pop(...)"),
        ("import os\nos.environ.update({})\n", "os.environ.update(...)"),
        ("import os\nos.environ.clear()\n", "os.environ.clear(...)"),
        ('import os\ndel os.environ["X"]\n', "del os.environ[...]"),
    ):
        tree = ast.parse(source)
        found = env_mutations(tree, _alias_map(tree))
        assert [what for _, what in found] == [expected], (source, found)


def test_an_aliased_module_import_does_not_evade_the_guard():
    source = "import os as _os\n_os.environ.update({'A': 'b'})\n"
    tree = ast.parse(source)

    assert env_mutations(tree, {}) == [], "bare-name matching should NOT see through the alias"
    assert [what for _, what in env_mutations(tree, _alias_map(tree))] == ["os.environ.update(...)"]


def test_a_from_import_of_environ_does_not_evade_the_guard():
    aliased = "from os import environ as _env\n_env['X'] = '1'\n"
    plain = "from os import environ\nenviron.setdefault('X', '1')\n"
    for source in (aliased, plain):
        tree = ast.parse(source)
        assert env_mutations(tree, {}) == [], f"bare-name matching should not see through: {source!r}"
        assert len(env_mutations(tree, _alias_map(tree))) == 1, source

    tree = ast.parse("environ = {}\nenviron['X'] = '1'\n")
    assert env_mutations(tree, _alias_map(tree)) == []


def test_putenv_is_covered_because_it_leaves_os_environ_stale():
    tree = ast.parse('import os\nos.putenv("X", "1")\nos.unsetenv("Y")\n')
    assert [what for _, what in env_mutations(tree, _alias_map(tree))] == ["os.putenv(...)", "os.unsetenv(...)"]


def test_reading_the_environment_is_not_flagged():
    for source in (
        'import os\nassert os.environ["VITE_API_URL"] == ""\n',
        'import os\nassert os.environ.get("GILJO_FORCE_HTTP") == "1"\n',
        'import os\nsaved = {k: os.environ.get(k) for k in ("A", "B")}\n',
        'import os\nif "X" in os.environ:\n    pass\n',
        "import os\nchild_env = {**os.environ}\n",
        "import os\nkeys = sorted(os.environ.keys())\n",
    ):
        tree = ast.parse(source)
        assert env_mutations(tree, _alias_map(tree)) == [], source


def test_monkeypatch_is_not_flagged():
    source = (
        "def test_x(monkeypatch):\n"
        '    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")\n'
        '    monkeypatch.delenv("GILJO_FORCE_HTTP", raising=False)\n'
    )
    tree = ast.parse(source)
    assert env_mutations(tree, _alias_map(tree)) == []
