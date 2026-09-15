# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import hashlib
import json
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version


REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = REPO_ROOT / "requirements.txt"
LOCK = REPO_ROOT / "requirements.lock"

HASH_PREFIX = "# requirements-txt-hash: sha256:"

PINNED_EXACT = {"fastapi": "0.139.2", "starlette": "1.3.1"}


pytestmark = pytest.mark.skipif(
    not LOCK.exists(),
    reason="requirements.lock absent — CI/Railway-only artifact, excluded from the CE export.",
)


def _normalize(dep_str: str) -> tuple:
    req = Requirement(dep_str)
    name = canonicalize_name(req.name)
    extras = tuple(sorted(canonicalize_name(e) for e in req.extras))
    specifiers = tuple(sorted(str(s) for s in req.specifier))
    return (name, extras, specifiers)


def _requirements_direct_deps() -> list[Requirement]:
    deps = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        deps.append(Requirement(line))
    return deps


def _canonical_dep_hash() -> str:
    deps = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        deps.append(_normalize(line))
    payload = json.dumps(sorted(deps), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _locked_versions() -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in LOCK.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, _, version = line.partition("==")
        version = version.split(";", 1)[0].split("#", 1)[0].strip()
        pins[canonicalize_name(name.strip())] = version
    return pins


def test_lock_satisfies_requirements():
    pins = _locked_versions()
    problems = []
    for req in _requirements_direct_deps():
        name = canonicalize_name(req.name)
        if name not in pins:
            problems.append(f"{name}: declared in requirements.txt but missing from requirements.lock")
            continue
        locked = pins[name]
        if req.specifier and not SpecifierSet(str(req.specifier)).contains(locked, prereleases=True):
            problems.append(f"{name}: locked {locked} does not satisfy requirements.txt '{req.specifier}'")

    assert not problems, (
        "requirements.lock is out of sync with requirements.txt. Regenerate it:\n"
        "    (run the requirements-lock generator)\n"
        "and commit both files.\n  " + "\n  ".join(problems)
    )


def test_pinned_core_unchanged():
    pins = _locked_versions()
    for name, expected in PINNED_EXACT.items():
        actual = pins.get(name)
        assert actual == expected, (
            f"requirements.lock has {name}=={actual}, expected {expected} "
            f"(INF-6053 pin — re-floating is a deliberate upgrade project, not a free bump)."
        )


def test_lock_header_hash_matches_requirements():
    header_hash = None
    for raw in LOCK.read_text(encoding="utf-8").splitlines():
        if raw.startswith(HASH_PREFIX):
            header_hash = raw[len(HASH_PREFIX) :].strip()
            break

    assert header_hash, (
        f"requirements.lock is missing its '{HASH_PREFIX}<hex>' header line. "
        "Regenerate it with the requirements-lock generator."
    )
    assert header_hash == _canonical_dep_hash(), (
        "requirements.txt changed without regenerating requirements.lock (dep-set hash mismatch).\n"
        "Run the requirements-lock generator and commit both files."
    )


def test_locked_versions_are_concrete():
    for version in _locked_versions().values():
        Version(version)
