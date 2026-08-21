# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-9432: nothing under ``tests/`` mutates ``os.environ`` directly.

The written law this enforces is CLAUDE.md's parallel-safe test discipline: "No
module-level mutable state. Use ``monkeypatch.setenv()`` or fixtures with
``yield + cleanup``, not ``os.environ[...] = ...``". It had nothing checking it,
and the population had grown to 23 inert sites plus two live leaks across 22
files before this guard existed.

WHAT MAKES THE ENV CASE DIFFERENT from its sibling guards. ``os.environ`` is
process-global and pytest-xdist runs each worker as one long-lived process, so a
mutation from any test persists for every test that follows it *on that worker* --
and which tests follow is a scheduling detail. The failure is therefore
order-dependent by construction: it appears on one worker, on some runs, against
a test that did not cause it. That is the signature the whole surrounding sprint
kept re-deriving as "a different victim every run", and it is why the fix has to
be mechanical rather than advisory.

The two shapes it caught when written, and why BOTH needed a mechanism:

* **23 inert calls** -- ``os.environ.setdefault("JWT_SECRET", "test_secret_key")``
  where ``tests/conftest.py`` had already set that key at import time, before any
  test module is loaded. Every one was a guaranteed no-op: dead code wearing the
  costume of process-global state. Harmless in effect, and precisely the reason
  the real ones hid so well -- a reader who has learned that these calls do
  nothing stops looking at them.
* **2 live leaks** -- ``os.environ.setdefault("GILJO_TENANT_GUARD_MODE", "enforce")``
  in ``tests/api/test_be6004c_websocket_tenant_scope.py``, a variable NOTHING sets
  in ``conftest.py``, in a tree where 34 other sites reach for
  ``monkeypatch.setenv`` for that same variable. The leak was outcome-silent only
  because unset and ``enforce`` mean the same thing to ``tenant_guard`` today, so
  the leaked value happened to equal the default. That is a vacuity, not a
  clearance: it becomes a moving failure the day anything asserts audit-by-default.
  ``setdefault`` also made those two fail-closed tests WEAKER than they read --
  had ``audit`` leaked in first, ``setdefault`` would have left it, and both tests
  would have passed while asserting nothing about the path they exist to pin.

READS ARE LEGAL, AND THAT IS LOAD-BEARING, not leniency. Two converted files
assert on production code that writes ``os.environ`` itself (``startup``'s
``resolve_ssl_decision`` and ``_patch_env_from_config``), so
``assert os.environ["VITE_API_URL"] == ""`` is the assertion, not the defect. This
walks the AST and discriminates Store/Del context from Load, which a substring
scan for ``os.environ`` cannot do -- it would have to flag the assertions to catch
the writes.

Import ALIASES are resolved per file. ``import os as _os`` then
``_os.environ.update(...)`` is a real form in this tree
(``tests/saas/test_alembic_dual_chain.py`` — the one allowlisted site, which is
also the one that proves the alias shape is not hypothetical), and ``from os
import environ`` hides the ``os.`` prefix a name match would key on. Both are
covered and both are proven below.

KNOWN LIMITS, stated rather than left to be discovered:

* A mutation reached through a runtime indirection -- ``getattr(os, "environ")``,
  ``d = os.environ`` then ``d["X"] = 1``, ``importlib`` -- is invisible here. This
  is a ratchet against the convention eroding, not a proof that no such mutation
  can exist. Measured when written: zero such sites.
* ``os.putenv`` / ``os.unsetenv`` are included because they mutate the real
  environment while leaving ``os.environ`` stale, so a scan aimed only at
  ``os.environ`` would call the more dangerous form clean. Measured: zero sites.

Edition Scope: Both (test-only guard).
"""

from __future__ import annotations

import ast
from pathlib import Path


_TESTS_ROOT = Path(__file__).resolve().parent.parent

# THE ALLOWLIST CRITERION, stated so it can be argued with rather than grown:
# a site is exempt ONLY when no monkeypatch primitive can express what it needs.
# "Converting is inconvenient" is never a reason -- conversion is the cheap fix in
# every other case, and an allowlist that admits inconvenience is where the class
# hides, which turns this guard into decoration.
#
# Two sites meet it today:
#
# * tests/conftest.py -- sets DB_PASSWORD and JWT_SECRET at IMPORT time, before any
#   test module is imported, because config validation runs at import of the
#   application package. There is no fixture and no monkeypatch at that point in
#   the lifecycle. This is genuinely bootstrap, and it is the reason all 23 inert
#   `setdefault` sites were inert.
#
# * tests/saas/test_alembic_dual_chain.py -- snapshots and restores the ENTIRE
#   environment (`clear()` + `update(saved)`) around loading the alembic runner
#   script by path, whose top-level `load_dotenv()` sets an OPEN set of keys that
#   the test cannot enumerate in advance. monkeypatch's primitives are all
#   per-key, so there is nothing to convert this to. It is also already the FIX
#   for this defect class rather than an instance of it: its own docstring records
#   that without the restore, the production `POSTGRES_DB=giljo_mcp` leaked into
#   the autouse `db_manager` safety guard and ERRORed sibling tests. Flagging it
#   would be asking it to reintroduce the leak.
_ALLOWED = {
    _TESTS_ROOT / "conftest.py",
    _TESTS_ROOT / "saas" / "test_alembic_dual_chain.py",
    Path(__file__).resolve(),
}

# Mutating members of os.environ (a MutableMapping). `get`, `keys`, `items`,
# `copy` and friends are deliberately absent: reading is legal.
_MUTATING_METHODS = {
    "setdefault",
    "pop",
    "popitem",
    "update",
    "clear",
    "__setitem__",
    "__delitem__",
}

# Module-level os functions that mutate the process environment WITHOUT going
# through os.environ, leaving it stale -- strictly worse than the forms above.
_MUTATING_OS_FUNCTIONS = {"putenv", "unsetenv"}


def _alias_map(tree: ast.Module) -> dict[str, str]:
    """Local name -> imported name, for every import in the module.

    ``import os as _os`` yields ``{"_os": "os"}`` and ``from os import environ as
    _env`` yields ``{"_env": "environ"}``, so both renames resolve back to the
    thing they name. Un-aliased imports map a name to itself, which is harmless.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                imported = alias.name.rsplit(".", 1)[-1]
                aliases[alias.asname or imported] = imported
    return aliases


def _is_os_environ(node: ast.expr, aliases: dict[str, str]) -> bool:
    """True when ``node`` is a reference to ``os.environ``, under any import shape.

    Handles ``os.environ`` / ``_os.environ`` (attribute on an aliased module) and
    bare ``environ`` / ``_env`` (``from os import environ [as _env]``). A local
    variable coincidentally named ``environ`` is NOT matched, because the name has
    to be in the module's import table to resolve.
    """
    if isinstance(node, ast.Attribute) and node.attr == "environ":
        base = getattr(node.value, "id", None)
        return base is not None and aliases.get(base, base) == "os"
    name = getattr(node, "id", None)
    return name is not None and aliases.get(name) == "environ"


def _is_os_function(node: ast.expr, aliases: dict[str, str], names: set[str]) -> bool:
    """True when ``node`` is ``os.<name>`` for a name in ``names``, aliases resolved."""
    if isinstance(node, ast.Attribute) and node.attr in names:
        base = getattr(node.value, "id", None)
        return base is not None and aliases.get(base, base) == "os"
    name = getattr(node, "id", None)
    return name is not None and aliases.get(name) in names


def env_mutations(tree: ast.Module, aliases: dict[str, str] | None = None) -> list[tuple[int, str]]:
    """Every direct environment mutation in ``tree``, as ``(lineno, what)`` pairs.

    Split out from the guard test so the mutation proofs below can drive the
    detector on source text without a file having to exist in the tree.
    """
    aliases = {} if aliases is None else aliases
    found: list[tuple[int, str]] = []

    def flag(node: ast.AST, what: str) -> None:
        found.append((getattr(node, "lineno", 0), what))

    for node in ast.walk(tree):
        # os.environ["X"] = ... / += ... / : t = ...   (Store context only)
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


# ---------------------------------------------------------------------------
# Mutation proofs. A guard nobody has watched fail is decoration -- and these are
# written in the shapes that would EVADE a naive implementation, not the shape the
# author expects to catch (the lesson INF-9417 paid for with a green run).
# ---------------------------------------------------------------------------


def test_the_guard_sees_the_plain_shapes():
    """The obvious forms, including the exact call this project burned down."""
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
    """``import os as _os`` then ``_os.environ.update(...)``.

    Not hypothetical: that exact form is in this tree at
    ``tests/saas/test_alembic_dual_chain.py``. A detector keyed on the literal
    prefix ``os.`` calls it clean, which would have made this guard advisory
    against the shape a mechanical re-introduction actually takes.
    """
    source = "import os as _os\n_os.environ.update({'A': 'b'})\n"
    tree = ast.parse(source)

    assert env_mutations(tree, {}) == [], "bare-name matching should NOT see through the alias"
    assert [what for _, what in env_mutations(tree, _alias_map(tree))] == ["os.environ.update(...)"]


def test_a_from_import_of_environ_does_not_evade_the_guard():
    """``from os import environ`` removes the ``os.`` prefix entirely.

    The harder half of the same evasion: here there is no attribute access to
    inspect at all, only a bare name, so the module's import table is the only
    thing that can tell ``environ`` the mapping from ``environ`` the local.
    """
    aliased = "from os import environ as _env\n_env['X'] = '1'\n"
    plain = "from os import environ\nenviron.setdefault('X', '1')\n"
    for source in (aliased, plain):
        tree = ast.parse(source)
        assert env_mutations(tree, {}) == [], f"bare-name matching should not see through: {source!r}"
        assert len(env_mutations(tree, _alias_map(tree))) == 1, source

    # ...and a local named `environ` that was never imported is NOT a false positive.
    tree = ast.parse("environ = {}\nenviron['X'] = '1'\n")
    assert env_mutations(tree, _alias_map(tree)) == []


def test_putenv_is_covered_because_it_leaves_os_environ_stale():
    """``os.putenv`` mutates the real environment WITHOUT updating ``os.environ``.

    A scan aimed only at ``os.environ`` would call the more dangerous form clean:
    the leak is invisible to every later reader of ``os.environ`` in the same
    process, while child processes see it.
    """
    tree = ast.parse('import os\nos.putenv("X", "1")\nos.unsetenv("Y")\n')
    assert [what for _, what in env_mutations(tree, _alias_map(tree))] == ["os.putenv(...)", "os.unsetenv(...)"]


def test_reading_the_environment_is_not_flagged():
    """The half that must stay legal, or the guard cannot be adopted.

    Two files converted by INF-9432 assert on production code that writes
    ``os.environ`` itself, so the READ is the assertion. A substring scan for
    ``os.environ`` would have to flag these to catch the writes.
    """
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
    """The prescribed replacement must obviously pass, or nobody converts to it."""
    source = (
        "def test_x(monkeypatch):\n"
        '    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")\n'
        '    monkeypatch.delenv("GILJO_FORCE_HTTP", raising=False)\n'
    )
    tree = ast.parse(source)
    assert env_mutations(tree, _alias_map(tree)) == []
