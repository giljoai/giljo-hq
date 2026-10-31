# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNED_DIRS = ("tests", "internal")
FIELDS = frozenset({"series_number", "serial"})


def _draws_randomly(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            owner = sub.func.value
            if isinstance(owner, ast.Name) and owner.id == "random":
                return True
    return False


def _target_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Attribute):
        return {target.attr}
    return set()


def _series_values(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg in FIELDS:
            yield node.value
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value in FIELDS:
                    yield value
        elif (isinstance(node, ast.Assign) and any(FIELDS & _target_names(t) for t in node.targets)) or (
            isinstance(node, ast.AnnAssign) and node.value is not None and FIELDS & _target_names(node.target)
        ):
            yield node.value


def _violations_in(source: str, label: str) -> list[str]:
    tree = ast.parse(source)
    return [f"{label}:{value.lineno}" for value in _series_values(tree) if _draws_randomly(value)]


def test_no_test_seeds_a_project_or_thread_serial_with_a_random_draw():
    found: list[str] = []
    for top in SCANNED_DIRS:
        for path in sorted((REPO_ROOT / top).rglob("*.py")):
            if "node_modules" in path.parts:
                continue
            found.extend(_violations_in(path.read_text(encoding="utf-8"), str(path.relative_to(REPO_ROOT))))
    assert not found, (
        "serial drawn at random (collides under uq_project_taxonomy_active or uq_comm_thread_serial); "
        "use tests.helpers.taxonomy_seeds.next_series_number() for projects or "
        "next_thread_serial() for Hub threads instead:\n  " + "\n  ".join(found)
    )


def test_the_scan_sees_every_shape_the_draw_was_written_in():
    shapes = {
        "kwarg": "Project(series_number=random.randint(1, 9000))",
        "pop default": 'Project(series_number=kwargs.pop("series_number", random.randint(1, 9999)))',
        "dict entry": '{"series_number": random.randint(1, 9000)}',
        "assignment": "project.series_number = random.randint(1, 9000)",
        "thread kwarg": "CommThread(serial=random.randint(1, 90000))",
        "thread assignment": "thread.serial = random.randint(1, 90000)",
    }
    for name, source in shapes.items():
        assert _violations_in(source, name), f"scan missed the {name} shape"


def test_the_scan_leaves_the_allocator_and_literals_alone():
    clean = (
        "Project(series_number=next_series_number())\n"
        "Project(series_number=42)\n"
        "CommThread(serial=next_thread_serial())\n"
        "CommThread(serial=1)\n"
        "Agent(name=random.choice(names))\n"
    )
    assert _violations_in(clean, "clean") == []


def test_the_allocator_stays_in_range_and_never_repeats_within_its_span():
    from tests.helpers.taxonomy_seeds import _SERIES_SPAN, _series_for

    values = [_series_for(index) for index in range(_SERIES_SPAN)]
    assert len(set(values)) == _SERIES_SPAN
    assert min(values) >= 1000 and max(values) <= 8999


def test_consecutive_seeds_leave_room_for_the_service_allocator():
    from tests.helpers.taxonomy_seeds import _series_for

    assert _series_for(1) - _series_for(0) == 100
    assert _series_for(80) == 1001


def test_thread_serials_have_their_own_counter_in_the_same_bounded_range():
    from tests.helpers.taxonomy_seeds import _series_for, next_series_number, next_thread_serial

    first, second = next_thread_serial(), next_thread_serial()
    assert 1000 <= first <= 8999 and 1000 <= second <= 8999
    assert first != second
    project_before = next_series_number()
    next_thread_serial()
    offset = project_before - 1000
    index_before = (offset % 100) * 80 + offset // 100
    assert next_series_number() == _series_for(index_before + 1)
