# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest

from giljo_mcp.system_roles import SYSTEM_MANAGED_ROLES
from giljo_mcp.template_seeder import _get_default_templates_v103, _seeded_user_instructions


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
REVISION_REGISTRY = REPO_ROOT / "migrations" / "revision_registry.json"

WORKER_PROSE_PINS: dict[str, str] = {
    "implementer": "b591b2818ca96ef144dad4e4a4290b6833774b9fba972592cd7bd02dec01f0cd",
    "tester": "caba4a347e0898330fe74d31d96e95f44c3c1b2eafad32cf1277ea6404f0478e",
    "analyzer": "70bead2ff143289fb63dab237f847e034adc71b4717d0c0f4de13422e7690f86",
    "reviewer": "32793527e6da03bc072897eab52c8a93d2f02cfdcf3f567c1df3a965a6235d80",
    "documenter": "7f9ffc1310b86e1d31f3d7fec01d5d2c20c660238aa8edae3ea3ee33c5564988",
}

WORKER_VERSION_PINS: dict[str, str] = {
    "implementer": "1.1.0",
    "tester": "1.2.0",
    "analyzer": "1.0.0",
    "reviewer": "1.0.0",
    "documenter": "1.1.0",
}

LATEST_HEAL_AT_PIN = "ce_0112_heal_worker_bootstrap_first_call"

GRANDFATHERED_HEALS: frozenset[str] = frozenset(
    {
        "ce_0049_heal_tool_rename_user_instructions",
        "ce_0090_heal_giljo_hq_orchestrator_identity",
    }
)

_HEAL_FILE = re.compile(r"^ce_(\d+)_heal_.+\.py$")
_HEAL_REVISION = re.compile(r"^ce_(\d+)_heal_")
_UPDATE_STMT = re.compile(r"update\s+agent_templates\b", re.IGNORECASE)
_SET_CLAUSE = re.compile(r"\bset\b(.*?)(?:\bwhere\b|$)", re.IGNORECASE | re.DOTALL)
_WHERE_CLAUSE = re.compile(r"\bwhere\b(.*)$", re.IGNORECASE | re.DOTALL)
_SET_COLUMN = re.compile(r"(\w+)\s*=")




def served_prose_hash(template_def: dict) -> str:
    return hashlib.sha256(_seeded_user_instructions(template_def).encode("utf-8")).hexdigest()


def worker_definitions() -> list[dict]:
    return [d for d in _get_default_templates_v103() if d["role"] not in SYSTEM_MANAGED_ROLES]


def heal_sequence(revision_id: str) -> int:
    match = _HEAL_REVISION.match(revision_id)
    if match is None:
        raise ValueError(f"{revision_id!r} is not a ce_NNNN_heal_* revision id")
    return int(match.group(1))


def heals_in_tree(versions_dir: Path = VERSIONS_DIR) -> dict[str, str]:
    return {
        p.stem: p.read_text(encoding="utf-8")
        for p in sorted(versions_dir.glob("ce_*_heal_*.py"))
        if _HEAL_FILE.match(p.name)
    }


def string_constants(source: str) -> list[str]:
    tree = ast.parse(source)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            out.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            out.append(
                "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
            )
    return out


def heal_names_role(source: str, role: str) -> bool:
    pattern = re.compile(rf"\b{re.escape(role)}\b")
    return any(pattern.search(s) for s in string_constants(source))


def prose_pin_violations(
    hashes: dict[str, str],
    pins: dict[str, str],
    heals: dict[str, str],
    latest_heal_at_pin: str,
) -> list[str]:
    floor = heal_sequence(latest_heal_at_pin)
    violations: list[str] = []
    for role, current in hashes.items():
        pinned = pins.get(role)
        if pinned is None:
            violations.append(f"{role}: new factory persona with no pin in WORKER_PROSE_PINS")
            continue
        if current == pinned:
            continue
        newer = [rev for rev, src in heals.items() if heal_sequence(rev) > floor and heal_names_role(src, role)]
        if not newer:
            violations.append(
                f"{role}: served prose changed (hash {current[:12]}, pinned {pinned[:12]}) with no "
                f"migrations/versions/ce_NNNN_heal_*.py newer than {latest_heal_at_pin} naming '{role}'. "
                "Existing installs hold a copy of the old text and nothing else reaches it: add a heal "
                "migration gated on byte-equality with the OLD text, then re-pin the hash and "
                "LATEST_HEAL_AT_PIN here."
            )
    return violations


def version_pin_violations(
    hashes: dict[str, str], versions: dict[str, str], prose_pins: dict[str, str], version_pins: dict[str, str]
) -> list[str]:
    return [
        f"{role}: served prose changed but the definition's version is still {versions[role]!r}; "
        "bump it in template_seeder.py and re-pin WORKER_VERSION_PINS"
        for role, current in hashes.items()
        if role in prose_pins and current != prose_pins[role] and versions.get(role) == version_pins.get(role)
    ]


def _sql_statements(source: str) -> list[str]:
    return [" ".join(s.split()) for s in string_constants(source) if _UPDATE_STMT.search(s)]


def heal_scan_violations(source: str) -> list[str]:
    statements = _sql_statements(source)
    if not statements:
        return [
            "no 'UPDATE agent_templates' SQL text found: write the heal as sa.text(\"UPDATE agent_templates "
            'SET <col> = :new WHERE ... <col> = :old") so this gate can read its guard'
        ]
    violations: list[str] = []
    for stmt in statements:
        head = stmt[:80]
        if re.search(r"\breplace\s*\(", stmt, re.IGNORECASE):
            violations.append(f"substring REPLACE rewrites user-edited text too: {head}")
        if re.search(r"\blike\b", stmt, re.IGNORECASE):
            violations.append(f"LIKE is a substring match, not a known-generation guard: {head}")
        if re.search(r"\bupdated_at\s+is\s+not\s+null\b", stmt, re.IGNORECASE):
            violations.append(f"targets user-edited rows (updated_at IS NOT NULL): {head}")
        where = _WHERE_CLAUSE.search(stmt)
        set_clause = _SET_CLAUSE.search(stmt)
        if where is None or set_clause is None:
            violations.append(f"no WHERE guard: {head}")
            continue
        for column in _SET_COLUMN.findall(set_clause.group(1)):
            if not re.search(rf"\b{re.escape(column)}\s*=\s*:\w+", where.group(1)):
                violations.append(
                    f"SET {column} is not gated on byte-equality of {column} with a known previous text "
                    f"(expected 'WHERE ... {column} = :old'): {head}"
                )
    return violations




def _current_hashes() -> dict[str, str]:
    return {d["role"]: served_prose_hash(d) for d in worker_definitions()}


def test_pins_cover_exactly_the_worker_roles():
    assert set(_current_hashes()) == set(WORKER_PROSE_PINS) == set(WORKER_VERSION_PINS)


def test_served_prose_change_ships_with_a_heal_migration():
    violations = prose_pin_violations(_current_hashes(), WORKER_PROSE_PINS, heals_in_tree(), LATEST_HEAL_AT_PIN)
    assert not violations, "\n".join(violations)


def test_served_prose_change_bumps_the_definition_version():
    versions = {d["role"]: d["version"] for d in worker_definitions()}
    violations = version_pin_violations(_current_hashes(), versions, WORKER_PROSE_PINS, WORKER_VERSION_PINS)
    assert not violations, "\n".join(violations)


def test_latest_heal_pin_is_the_newest_heal_in_tree_and_a_shipped_revision():
    heals = heals_in_tree()
    newest = max(heals, key=heal_sequence)
    assert newest == LATEST_HEAL_AT_PIN, (
        f"LATEST_HEAL_AT_PIN is {LATEST_HEAL_AT_PIN} but the newest heal in the tree is {newest}; "
        "point the pin at it so the next prose change needs a heal newer than this one"
    )
    known = json.loads(REVISION_REGISTRY.read_text(encoding="utf-8"))["known_revisions"]
    assert LATEST_HEAL_AT_PIN in known, f"{LATEST_HEAL_AT_PIN} is not in migrations/revision_registry.json"


def test_every_heal_migration_is_gated_on_byte_equality_or_grandfathered():
    failures = {
        rev: heal_scan_violations(src) for rev, src in heals_in_tree().items() if rev not in GRANDFATHERED_HEALS
    }
    failures = {rev: v for rev, v in failures.items() if v}
    assert not failures, "\n".join(f"{rev}: {msg}" for rev, msgs in failures.items() for msg in msgs)


def test_grandfather_list_names_only_heals_that_still_fail_the_scan():
    heals = heals_in_tree()
    missing = GRANDFATHERED_HEALS - set(heals)
    assert not missing, f"grandfathered heals not in the tree: {sorted(missing)}"
    compliant = [rev for rev in GRANDFATHERED_HEALS if not heal_scan_violations(heals[rev])]
    assert not compliant, f"these heals pass the scan and must leave GRANDFATHERED_HEALS: {compliant}"
    too_new = [rev for rev in GRANDFATHERED_HEALS if heal_sequence(rev) > heal_sequence(LATEST_HEAL_AT_PIN)]
    assert not too_new, f"a heal newer than the gate cannot be grandfathered: {too_new}"



_BYTE_EQUALITY_HEAL = """
import sqlalchemy as sa
from alembic import op

revision = "ce_0113_heal_tester_rules"
down_revision = "ce_0112_heal_worker_bootstrap_first_call"

_OLD = "You are the testing specialist (old generation)."
_NEW = "You are the testing specialist (new generation)."


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE agent_templates SET user_instructions = :new "
            "WHERE name = 'tester' AND user_instructions = :old"
        ),
        {"old": _OLD, "new": _NEW},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE agent_templates SET user_instructions = :old "
            "WHERE name = 'tester' AND user_instructions = :new"
        ),
        {"old": _OLD, "new": _NEW},
    )
"""

_SUBSTRING_REPLACE_HEAL = """
import sqlalchemy as sa
from alembic import op

revision = "ce_0113_heal_tool_rename"
down_revision = "ce_0112_heal_worker_bootstrap_first_call"
_NAMES = "'implementer', 'tester'"


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            f"UPDATE agent_templates "
            f"SET user_instructions = REPLACE(user_instructions, :old, :new) "
            f"WHERE name IN ({_NAMES}) AND user_instructions LIKE :pattern"
        ),
        {"old": "get_agent_mission", "new": "get_job_mission", "pattern": "%get_agent_mission%"},
    )
"""

_NAME_ONLY_GUARD_HEAL = """
import sqlalchemy as sa
from alembic import op

revision = "ce_0113_heal_tester_rules"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE agent_templates SET user_instructions = :new WHERE name = 'tester'"),
        {"new": "new text"},
    )
"""

_EDITED_ROWS_HEAL = """
import sqlalchemy as sa
from alembic import op

revision = "ce_0113_heal_tester_rules"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE agent_templates SET user_instructions = :new "
            "WHERE user_instructions = :old AND updated_at IS NOT NULL"
        ),
        {"old": "old", "new": "new"},
    )
"""

_ORM_HEAL = """
from alembic import op
from sqlalchemy import update
from giljo_mcp.models import AgentTemplate

revision = "ce_0113_heal_tester_rules"


def upgrade() -> None:
    op.get_bind().execute(update(AgentTemplate).values(user_instructions="new"))
"""


def _perturbed(hashes: dict[str, str], role: str) -> dict[str, str]:
    return {**hashes, role: hashlib.sha256(b"changed prose").hexdigest()}


def test_gate_fails_on_prose_change_without_a_heal():
    hashes = _current_hashes()
    violations = prose_pin_violations(
        _perturbed(hashes, "tester"), WORKER_PROSE_PINS, heals_in_tree(), LATEST_HEAL_AT_PIN
    )
    assert len(violations) == 1
    assert violations[0].startswith("tester: served prose changed")
    assert "ce_NNNN_heal_" in violations[0]


def test_gate_passes_prose_change_with_a_newer_heal_naming_the_role():
    hashes = _current_hashes()
    heals = {**heals_in_tree(), "ce_0113_heal_tester_rules": _BYTE_EQUALITY_HEAL}
    assert prose_pin_violations(_perturbed(hashes, "tester"), WORKER_PROSE_PINS, heals, LATEST_HEAL_AT_PIN) == []


def test_gate_ignores_a_newer_heal_that_names_another_role():
    hashes = _current_hashes()
    heals = {**heals_in_tree(), "ce_0113_heal_tester_rules": _BYTE_EQUALITY_HEAL}
    violations = prose_pin_violations(_perturbed(hashes, "reviewer"), WORKER_PROSE_PINS, heals, LATEST_HEAL_AT_PIN)
    assert [v.split(":")[0] for v in violations] == ["reviewer"]


def test_gate_ignores_an_old_heal_even_when_it_names_the_role():
    hashes = _current_hashes()
    heals = {rev: src for rev, src in heals_in_tree().items() if rev == "ce_0049_heal_tool_rename_user_instructions"}
    assert heal_names_role(heals["ce_0049_heal_tool_rename_user_instructions"], "analyzer")
    violations = prose_pin_violations(_perturbed(hashes, "analyzer"), WORKER_PROSE_PINS, heals, LATEST_HEAL_AT_PIN)
    assert len(violations) == 1


def test_gate_fails_on_a_new_persona_with_no_pin():
    hashes = {**_current_hashes(), "designer": hashlib.sha256(b"designer prose").hexdigest()}
    violations = prose_pin_violations(hashes, WORKER_PROSE_PINS, heals_in_tree(), LATEST_HEAL_AT_PIN)
    assert violations == ["designer: new factory persona with no pin in WORKER_PROSE_PINS"]


def test_version_gate_fails_when_prose_changes_and_version_does_not():
    hashes = _perturbed(_current_hashes(), "documenter")
    versions = dict(WORKER_VERSION_PINS)
    assert len(version_pin_violations(hashes, versions, WORKER_PROSE_PINS, WORKER_VERSION_PINS)) == 1
    versions["documenter"] = "1.2.0"
    assert version_pin_violations(hashes, versions, WORKER_PROSE_PINS, WORKER_VERSION_PINS) == []


def test_scan_accepts_a_byte_equality_gated_heal():
    assert heal_scan_violations(_BYTE_EQUALITY_HEAL) == []


def test_scan_rejects_a_substring_replace_heal():
    violations = heal_scan_violations(_SUBSTRING_REPLACE_HEAL)
    assert any("REPLACE" in v for v in violations)
    assert any("LIKE" in v for v in violations)
    assert any("not gated on byte-equality of user_instructions" in v for v in violations)


def test_scan_rejects_a_heal_guarded_on_name_alone():
    violations = heal_scan_violations(_NAME_ONLY_GUARD_HEAL)
    assert violations and all("not gated on byte-equality of user_instructions" in v for v in violations)


def test_scan_rejects_a_heal_that_targets_user_edited_rows():
    violations = heal_scan_violations(_EDITED_ROWS_HEAL)
    assert len(violations) == 1 and violations[0].startswith("targets user-edited rows (updated_at IS NOT NULL)")


def test_scan_rejects_a_heal_it_cannot_read():
    violations = heal_scan_violations(_ORM_HEAL)
    assert len(violations) == 1 and violations[0].startswith("no 'UPDATE agent_templates' SQL text found")


@pytest.mark.parametrize("revision", sorted(GRANDFATHERED_HEALS))
def test_grandfathered_heals_fail_for_the_documented_reason(revision):
    violations = heal_scan_violations(heals_in_tree()[revision])
    assert any("REPLACE" in v for v in violations), violations
