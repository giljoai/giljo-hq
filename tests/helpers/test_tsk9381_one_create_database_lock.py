# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from pathlib import Path

from tests.helpers.test_db_helper import DB_CREATE_LOCK_KEY


_TESTS_ROOT = Path(__file__).resolve().parent.parent
_HELPER = _TESTS_ROOT / "helpers" / "test_db_helper.py"

_ADVISORY_CALL = re.compile(r"pg_advisory_(?:un)?lock\s*\(")
_LOCK_KEY_LITERAL = re.compile(r"^\s*_?[A-Z_]*LOCK_KEY[A-Z_]*\s*=\s*(\d+)", re.MULTILINE)


def _python_sources() -> list[Path]:
    return [p for p in _TESTS_ROOT.rglob("*.py") if "__pycache__" not in p.parts]


def test_the_advisory_lock_statements_live_only_in_the_shared_helper():
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
