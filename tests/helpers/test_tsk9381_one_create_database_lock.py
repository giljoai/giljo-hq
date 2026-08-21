# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-9381 — there is exactly ONE CREATE DATABASE advisory-lock key.

``CREATE DATABASE`` copies ``template1``. Two sessions copying it at once fail
with *"source database template1 is being accessed by other users"*, so every
create site in the suite has to hold the SAME advisory lock. Holding a different
key is indistinguishable from holding no lock at all.

That is precisely what had happened. The migration scratch-DB bootstrap defined
its own ``_SCRATCH_CREATE_LOCK_KEY = 7281643`` under a comment claiming the
"same serialization key family as the main test-DB bootstrap" — which held
7281642. The comment recorded the intent; the code excluded nothing. Nobody
noticed because the failure mode is a rare setup error under load, never a
reproducible test failure.

This is a SINGLE-SOURCE-OF-TRUTH guard, not a behaviour test: it fails if a new
site hand-rolls ``pg_advisory_lock`` for a create instead of using
``create_database_lock`` / ``create_database_lock_async``. A source scan is the
right shape because the defect is invisible at runtime — the wrong key still
"works", it just stops serializing.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.helpers.test_db_helper import DB_CREATE_LOCK_KEY


_TESTS_ROOT = Path(__file__).resolve().parent.parent
_HELPER = _TESTS_ROOT / "helpers" / "test_db_helper.py"

# ``pg_advisory_lock(<literal int>)`` or a bound param whose value is a literal
# assigned nearby. We scan for the raw statement and for any 728164x-shaped key
# constant, which is what a copy-paste of the original pair looks like.
_ADVISORY_CALL = re.compile(r"pg_advisory_(?:un)?lock\s*\(")
_LOCK_KEY_LITERAL = re.compile(r"^\s*_?[A-Z_]*LOCK_KEY[A-Z_]*\s*=\s*(\d+)", re.MULTILINE)


def _python_sources() -> list[Path]:
    return [p for p in _TESTS_ROOT.rglob("*.py") if "__pycache__" not in p.parts]


def test_the_advisory_lock_statements_live_only_in_the_shared_helper():
    """Only ``test_db_helper`` may issue the lock/unlock pair itself.

    Everything else goes through the two context managers, so there is one place
    where the key can be got wrong — and one place to change it if it ever needs
    changing.
    """
    offenders = sorted(
        str(path.relative_to(_TESTS_ROOT))
        for path in _python_sources()
        if path != _HELPER
        and path != Path(__file__).resolve()
        and _ADVISORY_CALL.search(path.read_text(encoding="utf-8"))
    )
    assert offenders == [], (
        "These files issue pg_advisory_lock directly instead of using "
        "create_database_lock / create_database_lock_async from "
        f"tests/helpers/test_db_helper.py: {offenders}. A create site with its own "
        "key does not serialize against the others — it only looks like it does."
    )


def test_no_second_create_database_lock_key_is_defined_anywhere():
    """A ``*LOCK_KEY = <int>`` constant may only exist with the one shared value."""
    rogue: list[str] = []
    for path in _python_sources():
        if path == Path(__file__).resolve():
            continue
        for value in _LOCK_KEY_LITERAL.findall(path.read_text(encoding="utf-8")):
            if int(value) != DB_CREATE_LOCK_KEY:
                rogue.append(f"{path.relative_to(_TESTS_ROOT)} -> {value}")

    assert rogue == [], (
        "A second CREATE DATABASE lock key was introduced: "
        f"{rogue}. template1 is ONE resource; a second key serializes nothing. "
        f"Use DB_CREATE_LOCK_KEY ({DB_CREATE_LOCK_KEY})."
    )
