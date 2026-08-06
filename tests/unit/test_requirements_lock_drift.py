# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""CI drift guard: requirements.lock must stay consistent with requirements.txt.

**Edition Scope:** Both — but the lock itself is consumed only by CI + the
Railway prod Dockerfile (pip install -r requirements.lock). install.py (CE
self-hosters) stays on requirements.txt this pass, and the lock is excluded from
the CE export. So when the lock is absent (e.g. the ce-export-test artifact),
this gate skips; in the full private tree (the `test`/`test-saas` jobs) it runs.

INF-6054. requirements.txt carries loose floors with no pinning, so a fresh
install could resolve a newer upstream release and silently drift (the
fastapi 0.137 / starlette 1.3.1 break). requirements.lock pins the whole
resolved tree. This test makes silent drift impossible: editing requirements.txt
without regenerating the lock REDs CI.

Two independent checks:
  1. Every requirements.txt direct dep is present in the lock AND the locked
     version satisfies the requirements.txt specifier (catches a stale/wrong
     pin, e.g. lock fastapi==0.135.3 while requirements.txt says ==0.137.1).
  2. The canonical direct-dep-set hash stamped in the lock header matches a
     freshly-computed hash of requirements.txt (catches a requirements.txt dep
     add/remove/bump that was committed without regenerating the lock — even
     when check 1 would still pass, e.g. a removed dep).

Regenerate the lock with the requirements-lock generator.

Parallel-safe: pure file parsing, no DB, no network, no module-level mutable
state. Scope is RUNTIME deps only — dev/optional extras are not locked.
"""

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

# Sanity floor for the deliberately-pinned core (INF-6053; deferral now lifted):
# the lock must keep these exact, or the route-surface snapshot tests break / the
# starlette CVEs (CVE-2026-48818/48817/54283/54282, fixed >=1.3.1) regress. The
# fastapi 0.137 _IncludedRouter route-surface change is handled by flattening in
# tests/helpers/route_surface.py.
# 2026-07-22: fastapi pin deliberately moved 0.139.0 -> 0.139.2 (operator-approved
# incremental update, not a re-float); starlette floor is unchanged. Route-surface
# tests confirmed green on 0.139.2 (CI run 4453).
PINNED_EXACT = {"fastapi": "0.139.2", "starlette": "1.3.1"}


pytestmark = pytest.mark.skipif(
    not LOCK.exists(),
    reason="requirements.lock absent — CI/Railway-only artifact, excluded from the CE export.",
)


def _normalize(dep_str: str) -> tuple:
    """(canonical name, sorted extras, sorted specifiers) — identical to
    the requirements-lock generator and test_dependency_manifest_sync.py."""
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
    """sha256 of the canonical direct-dep SET of requirements.txt (must match
    the requirements-lock generator's canonical_dep_hash exactly)."""
    deps = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        deps.append(_normalize(line))
    payload = json.dumps(sorted(deps), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _locked_versions() -> dict[str, str]:
    """canonical name -> pinned version, from the `name==version` lines."""
    pins: dict[str, str] = {}
    for raw in LOCK.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, _, version = line.partition("==")
        # Strip any trailing environment marker / inline comment.
        version = version.split(";", 1)[0].split("#", 1)[0].strip()
        pins[canonicalize_name(name.strip())] = version
    return pins


def test_lock_satisfies_requirements():
    """Every requirements.txt direct dep is locked at a version that satisfies it."""
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
    """fastapi / starlette stay at the INF-6053 last-known-good pins."""
    pins = _locked_versions()
    for name, expected in PINNED_EXACT.items():
        actual = pins.get(name)
        assert actual == expected, (
            f"requirements.lock has {name}=={actual}, expected {expected} "
            f"(INF-6053 pin — re-floating is a deliberate upgrade project, not a free bump)."
        )


def test_lock_header_hash_matches_requirements():
    """The dep-set hash in the lock header matches requirements.txt.

    Mismatch => requirements.txt was changed without regenerating the lock.
    """
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
    """Defensive: every lock pin is a valid PEP 440 version (catches a malformed lock)."""
    for version in _locked_versions().values():
        # Raises InvalidVersion on a malformed pin.
        Version(version)
