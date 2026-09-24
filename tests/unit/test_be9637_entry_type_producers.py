# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import get_args

import giljo_mcp.services  # noqa: F401  (warms the package; pre-existing import-order quirk)
from api.endpoints.mcp_tools._memory_tools import _EntryType
from giljo_mcp.tools import write_memory_entry as _write_memory_entry
from giljo_mcp.tools.write_memory_entry import (
    ENTRY_TYPE_ALIASES,
    RETIRED_ENTRY_TYPES,
    VALID_ENTRY_TYPES,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCANNED_ROOTS = ("src", "api", "internal")

_EMITS = re.compile(r"""["']?\bentry_type\b["']?\s*[=:]\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")

ACCEPTED = VALID_ENTRY_TYPES | set(ENTRY_TYPE_ALIASES)

_DEFINING_MODULE = Path(_write_memory_entry.__file__).resolve()


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in _SCANNED_ROOTS:
        base = _REPO_ROOT / root
        if not base.is_dir():
            continue
        files.extend(p for p in base.rglob("*.py") if "__pycache__" not in p.parts and p.name != "__init__.py")
    return sorted(files)


def _rel(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


def test_the_producer_scan_actually_reaches_the_tree() -> None:
    files = _python_files()
    assert len(files) > 100, f"the producer scan found only {len(files)} files; it is not reaching the tree"
    reached = {_rel(p).split("/", 1)[0] for p in files}
    for required in ("src", "api"):
        assert required in reached, f"the scan reached no file under {required}/"


def test_the_boundary_and_the_service_accept_the_same_values() -> None:
    boundary = set(get_args(_EntryType))
    assert boundary == ACCEPTED, (
        "the MCP boundary Literal and the service's accepted set have drifted.\n"
        f"  only at the boundary: {sorted(boundary - ACCEPTED)}\n"
        f"  only in the service:  {sorted(ACCEPTED - boundary)}"
    )


def test_no_code_path_emits_an_entry_type_the_validator_would_reject() -> None:
    offenders: list[str] = []
    for path in _python_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for value in _EMITS.findall(line):
                if value not in ACCEPTED:
                    why = "RETIRED" if value in RETIRED_ENTRY_TYPES else "never accepted"
                    offenders.append(f"  {_rel(path)}:{lineno}: entry_type={value!r} ({why})")

    assert not offenders, (
        "code emits or instructs an entry_type the server would reject:\n"
        + "\n".join(offenders)
        + f"\n\nAccepted values: {sorted(ACCEPTED)}."
        "\nIf this is a generated prompt, the agent reading it will make a call that "
        "fails, and no test other than this one will notice."
    )


def test_no_string_literal_sends_anyone_looking_for_a_retired_entry_type() -> None:
    offenders: list[str] = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover - a broken file is another test's problem
            continue
        defines_the_list = path.resolve() == _DEFINING_MODULE
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            text = node.value
            if defines_the_list and text in RETIRED_ENTRY_TYPES:
                continue
            if "BE-9637" in text:
                continue
            for retired in sorted(RETIRED_ENTRY_TYPES):
                if retired in text:
                    offenders.append(f"  {_rel(path)}:{node.lineno}: names retired entry type {retired!r}")

    assert not offenders, (
        "retired entry types are still named in agent-readable text:\n"
        + "\n".join(sorted(set(offenders)))
        + "\n\nA handover is a task of type HND now. If you genuinely need to mention "
        "the retired name (documenting why it is gone), say BE-9637 in the same string "
        "and this guard will allow it."
    )


def test_both_prongs_can_actually_fire() -> None:
    assert _EMITS.findall('    entry_type="handover_closeout",') == ["handover_closeout"]
    assert _EMITS.findall('        "entry_type": "session_handover",') == ["session_handover"]
    assert _EMITS.findall("write(entry_type='project_completion')") == ["project_completion"]
    assert _EMITS.findall("    entry_type = Column(String(50))") == []
    assert _EMITS.findall("    entry_type: str = Field(..., description='x')") == []
    assert _EMITS.findall("    entry_type = ENTRY_TYPE_ALIASES.get(entry_type, entry_type)") == []

    sample = 'Look for the most recent "handover_closeout" entry'
    assert any(r in sample for r in RETIRED_ENTRY_TYPES)
    excused = "handover_closeout is no longer accepted (BE-9637)"
    assert "BE-9637" in excused

    assert "handover_closeout" in RETIRED_ENTRY_TYPES
    assert "see the handover_closeout entry" not in RETIRED_ENTRY_TYPES

    assert not (RETIRED_ENTRY_TYPES & ACCEPTED), "a retired value is still accepted"
