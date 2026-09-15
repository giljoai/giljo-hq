# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
REQUIREMENTS = REPO_ROOT / "requirements.txt"


def _normalize(dep_str: str) -> tuple:
    req = Requirement(dep_str)
    name = canonicalize_name(req.name)
    extras = tuple(sorted(canonicalize_name(e) for e in req.extras))
    specifiers = tuple(sorted(str(s) for s in req.specifier))
    return (name, extras, specifiers)


def _pyproject_runtime_deps() -> set:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    return {_normalize(d) for d in deps}


def _requirements_runtime_deps() -> set:
    deps = set()
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-"):
            continue
        deps.add(_normalize(line))
    return deps


def test_manifests_are_in_sync():
    pyproject = _pyproject_runtime_deps()
    requirements = _requirements_runtime_deps()

    only_in_pyproject = pyproject - requirements
    only_in_requirements = requirements - pyproject

    def _fmt(items):
        return sorted(name + ("[" + ",".join(extras) + "]" if extras else "") for name, extras, _ in items)

    assert pyproject == requirements, (
        "Dependency manifests have drifted. Reconcile so both list the same runtime deps "
        "(requirements.txt is the source of truth).\n"
        f"  In pyproject.toml but NOT requirements.txt: {_fmt(only_in_pyproject)}\n"
        f"  In requirements.txt but NOT pyproject.toml: {_fmt(only_in_requirements)}"
    )
