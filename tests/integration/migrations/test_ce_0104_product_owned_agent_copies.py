# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from tests.helpers.test_db_helper import bootstrap_db_base, worker_suffix


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"

SCRATCH_DB = f"{bootstrap_db_base()}{worker_suffix()}"
ADMIN_USER = os.environ.get("POSTGRES_OWNER_USER", "giljo_owner")
ADMIN_PASSWORD = os.environ.get("POSTGRES_OWNER_PASSWORD", "")
DB_HOST = os.environ.get("POSTGRES_HOST", "localhost")
DB_PORT = os.environ.get("POSTGRES_PORT", "5432")

PRODUCTION_DB_NAME = "giljo_mcp"

_PRE = "ce_0103_be9605b_template_model_effort"
_REV = "ce_0104_be9610a_product_owned_agent_copies"


def _scratch_db_url() -> str:
    if SCRATCH_DB == PRODUCTION_DB_NAME:
        raise RuntimeError(
            "SAFETY GUARD: Refusing to run migration regression tests against the "
            "production DB name 'giljo_mcp'. Override GILJO_BOOTSTRAP_TEST_DB."
        )
    pw = ADMIN_PASSWORD
    if not pw:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("POSTGRES_OWNER_PASSWORD="):
                    pw = line.split("=", 1)[1].strip()
                    break
    if not pw:
        raise RuntimeError("POSTGRES_OWNER_PASSWORD is not set; cannot connect to scratch DB.")
    return f"postgresql://{ADMIN_USER}:{pw}@{DB_HOST}:{DB_PORT}/{SCRATCH_DB}"


def _scratch_engine() -> sa.Engine:
    return sa.create_engine(_scratch_db_url(), poolclass=sa.pool.NullPool)


def _drop_all_objects(engine: sa.Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text(f"GRANT ALL ON SCHEMA public TO {ADMIN_USER}"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        conn.commit()


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    url = _scratch_db_url()
    env["DATABASE_URL"] = url
    env["POSTGRES_HOST"] = DB_HOST
    env["POSTGRES_PORT"] = DB_PORT
    env["POSTGRES_DB"] = SCRATCH_DB
    env["POSTGRES_USER"] = ADMIN_USER
    env["DB_HOST"] = DB_HOST
    env["DB_PORT"] = DB_PORT
    env["DB_NAME"] = SCRATCH_DB
    env["DB_USER"] = ADMIN_USER
    pwd = url.split("//", 1)[1].split("@", 1)[0].split(":", 1)[1]
    env["POSTGRES_PASSWORD"] = pwd
    env["DB_PASSWORD"] = pwd
    env.pop("GILJO_MODE", None)
    return env


def _run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=str(PROJECT_ROOT),
        env=_build_env(),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _ensure_scratch_database_exists() -> None:
    scratch = _scratch_db_url()
    prefix, _, _ = scratch.rpartition("/")
    eng = sa.create_engine(f"{prefix}/postgres", poolclass=sa.pool.NullPool, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as conn:
            existing = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": SCRATCH_DB},
            ).scalar()
            if not existing:
                conn.execute(text(f'CREATE DATABASE "{SCRATCH_DB}" OWNER "{ADMIN_USER}"'))
    finally:
        eng.dispose()


@pytest.fixture(scope="module")
def scratch_engine():
    _ensure_scratch_database_exists()
    eng = _scratch_engine()
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield eng
    eng.dispose()




def _product(conn, pid: str, tk: str, name: str, *, is_active: bool = True, is_default: bool = False) -> None:
    conn.execute(
        text(
            "INSERT INTO products (id, name, slug, description, tenant_key, is_active, is_default, product_memory) "
            "VALUES (:id, :name, :slug, 'ce_0104 fixture', :tk, :act, :dflt, CAST('{}' AS JSONB))"
        ),
        {
            "id": pid,
            "name": name,
            "slug": name.lower().replace(" ", "-")[:60],
            "tk": tk,
            "act": is_active,
            "dflt": is_default,
        },
    )


def _template(conn, tid: str, tk: str, name: str, *, role: str = "implementer", is_active: bool = True) -> None:
    conn.execute(
        text(
            "INSERT INTO agent_templates "
            "(id, tenant_key, product_id, name, category, role, system_instructions, user_instructions, "
            " tool, cli_tool, version, is_active, is_default, tags) "
            "VALUES (:id, :tk, NULL, :name, 'role', :role, 'sys', 'body', 'claude', 'claude', '1.0.0', "
            "        :act, FALSE, CAST('[]' AS JSONB))"
        ),
        {"id": tid, "tk": tk, "name": name, "role": role, "act": is_active},
    )


def _assign(conn, aid: str, tk: str, pid: str, tid: str, *, is_active: bool) -> None:
    conn.execute(
        text(
            "INSERT INTO product_agent_assignments (id, product_id, template_id, tenant_key, is_active) "
            "VALUES (:id, :pid, :tid, :tk, :act)"
        ),
        {"id": aid, "pid": pid, "tid": tid, "tk": tk, "act": is_active},
    )


def _enabled_pairs(conn, tk: str) -> set[tuple[str, str]]:
    rows = conn.execute(
        text(
            "SELECT a.product_id, t.name FROM product_agent_assignments a "
            "JOIN agent_templates t ON t.id = a.template_id "
            "WHERE a.tenant_key = :tk AND a.is_active IS TRUE AND t.deleted_at IS NULL"
        ),
        {"tk": tk},
    ).fetchall()
    return {(r[0], r[1]) for r in rows}


def _names(conn, tk: str) -> set[str]:
    rows = conn.execute(
        text("SELECT name FROM agent_templates WHERE tenant_key = :tk AND deleted_at IS NULL"),
        {"tk": tk},
    ).fetchall()
    return {r[0] for r in rows}


def _upgrade_to_pre(engine: sa.Engine) -> None:
    _drop_all_objects(engine)
    up = _run_alembic("upgrade", _PRE)
    assert up.returncode == 0, f"upgrade to {_PRE} failed:\n{up.stdout}\n{up.stderr}"


def _upgrade_to_rev() -> None:
    up = _run_alembic("upgrade", _REV)
    assert up.returncode == 0, f"upgrade to {_REV} failed:\n{up.stdout}\n{up.stderr}"



CORRECT_TK = "tk_ce0104_already_correct"

CORRECT_PRODUCTS = [
    (
        "571459f3-0000-4000-8000-000000000001",
        "SaaS edition",
        [
            "analyzer",
            "documenter",
            "implementer-backend",
            "implementer-devops",
            "implementer-frontend",
            "reviewer",
            "tester",
        ],
    ),
    (
        "67a16461-0000-4000-8000-000000000002",
        "Memory Hub",
        [f"{r}-gmh" for r in ("analyzer", "documenter", "implementer", "planner", "reviewer", "tester", "writer")],
    ),
    (
        "a06edc43-0000-4000-8000-000000000003",
        "Codebase Auditor",
        [f"{r}-duplicate" for r in ("analyzer", "documenter", "reviewer", "tester", "planner")] + ["implementer"],
    ),
    ("aa073991-0000-4000-8000-000000000004", "Website", ["implementer-website"]),
    (
        "e4664da1-0000-4000-8000-000000000005",
        "Yapper",
        [f"{r}-yapper" for r in ("analyzer", "documenter", "implementer", "planner", "reviewer", "tester", "writer")],
    ),
]

CORRECT_RETIRED = {
    "analyzer",
    "documenter",
    "implementer-backend",
    "implementer-devops",
    "implementer-frontend",
    "reviewer",
    "tester",
}


@pytest.fixture
def already_correct_seeded(scratch_engine: sa.Engine):
    _upgrade_to_pre(scratch_engine)
    with scratch_engine.connect() as conn:
        all_names: list[str] = []
        for idx, (pid, pname, agents) in enumerate(CORRECT_PRODUCTS):
            _product(conn, pid, CORRECT_TK, pname, is_default=(idx == 0))
            all_names.extend(agents)

        tid_by_name = {}
        for n, name in enumerate(all_names):
            tid = f"dead0104-0000-4000-8000-{n:012d}"
            tid_by_name[name] = tid
            _template(conn, tid, CORRECT_TK, name, is_active=name not in CORRECT_RETIRED)

        a = 0
        for pid, _pname, own in CORRECT_PRODUCTS:
            for name in all_names:
                if name in own or a % 3 == 0:
                    _assign(
                        conn,
                        f"assn0104-0000-4000-8000-{a:012d}",
                        CORRECT_TK,
                        pid,
                        tid_by_name[name],
                        is_active=name in own,
                    )
                a += 1
        conn.commit()
    return scratch_engine


def test_an_already_correct_account_migrates_with_zero_copies_and_zero_renames(already_correct_seeded: sa.Engine):
    with already_correct_seeded.connect() as conn:
        names_before = _names(conn, CORRECT_TK)
        enabled_before = _enabled_pairs(conn, CORRECT_TK)
        count_before = len(names_before)

    _upgrade_to_rev()

    with already_correct_seeded.connect() as conn:
        names_after = _names(conn, CORRECT_TK)
        enabled_after = _enabled_pairs(conn, CORRECT_TK)

        assert names_after == names_before, (
            f"ce_0104 renamed or added agents on an account with nothing shared. "
            f"Added: {sorted(names_after - names_before)}; removed: {sorted(names_before - names_after)}"
        )
        assert len(names_after) == count_before == sum(len(agents) for _p, _n, agents in CORRECT_PRODUCTS)
        assert enabled_after == enabled_before, "A switch moved. The user's toggles must be copied EXACTLY."

        unowned = conn.execute(
            text(
                "SELECT COUNT(*) FROM agent_templates "
                "WHERE tenant_key = :tk AND deleted_at IS NULL AND product_id IS NULL"
            ),
            {"tk": CORRECT_TK},
        ).scalar()
        assert unowned == 0, "Every live agent must end up owned by exactly one product."


def test_stuck_seven_product_advertises_its_agents_again(already_correct_seeded: sa.Engine):
    stuck_product = CORRECT_PRODUCTS[0][0]

    with already_correct_seeded.connect() as conn:
        served_before = conn.execute(
            text(
                "SELECT COUNT(*) FROM product_agent_assignments a "
                "JOIN agent_templates t ON t.id = a.template_id "
                "WHERE a.product_id = :pid AND a.is_active IS TRUE "
                "AND t.is_active IS TRUE AND t.deleted_at IS NULL"
            ),
            {"pid": stuck_product},
        ).scalar()
        assert served_before == 0, "fixture is wrong: this product is supposed to be serving nothing"

    _upgrade_to_rev()

    with already_correct_seeded.connect() as conn:
        served_after = conn.execute(
            text(
                "SELECT COUNT(*) FROM product_agent_assignments a "
                "JOIN agent_templates t ON t.id = a.template_id "
                "WHERE a.product_id = :pid AND a.is_active IS TRUE AND t.deleted_at IS NULL"
            ),
            {"pid": stuck_product},
        ).scalar()
        assert served_after == 7, f"stuck product should serve its 7 agents again, serves {served_after}"

        stale = conn.execute(
            text(
                "SELECT COUNT(*) FROM agent_templates "
                "WHERE tenant_key = :tk AND deleted_at IS NULL AND is_active IS NOT TRUE"
            ),
            {"tk": CORRECT_TK},
        ).scalar()
        assert stale == 0, "the inert retire flag should have no stale false values left"


def test_no_live_product_is_left_without_explicit_rows(already_correct_seeded: sa.Engine):
    _upgrade_to_rev()

    with already_correct_seeded.connect() as conn:
        rowless = conn.execute(
            text(
                "SELECT p.id FROM products p WHERE p.tenant_key = :tk AND p.deleted_at IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM product_agent_assignments a WHERE a.product_id = p.id)"
            ),
            {"tk": CORRECT_TK},
        ).fetchall()
        assert rowless == [], f"live products left with no junction rows: {[r[0] for r in rowless]}"



SHARED_TK = "tk_ce0104_shared"
P1 = "11111111-0000-4000-8000-000000000001"
P2 = "22222222-0000-4000-8000-000000000002"
P3 = "33333333-0000-4000-8000-000000000003"
P4 = "44444444-0000-4000-8000-000000000004"


@pytest.fixture
def shared_seeded(scratch_engine: sa.Engine):
    _upgrade_to_pre(scratch_engine)
    with scratch_engine.connect() as conn:
        _product(conn, P1, SHARED_TK, "Alpha", is_default=True)
        _product(conn, P2, SHARED_TK, "Beta")
        _product(conn, P3, SHARED_TK, "Gamma", is_active=False)
        _product(conn, P4, SHARED_TK, "Delta")

        _template(conn, "5ha4ed01-0000-4000-8000-000000000001", SHARED_TK, "tester", role="tester")
        _template(conn, "50100001-0000-4000-8000-000000000002", SHARED_TK, "solo-agent", role="analyzer")

        _assign(
            conn,
            "a0000001-0000-4000-8000-000000000001",
            SHARED_TK,
            P1,
            "5ha4ed01-0000-4000-8000-000000000001",
            is_active=True,
        )
        _assign(
            conn,
            "a0000002-0000-4000-8000-000000000002",
            SHARED_TK,
            P2,
            "5ha4ed01-0000-4000-8000-000000000001",
            is_active=True,
        )
        _assign(
            conn,
            "a0000003-0000-4000-8000-000000000003",
            SHARED_TK,
            P3,
            "5ha4ed01-0000-4000-8000-000000000001",
            is_active=True,
        )
        _assign(
            conn,
            "a0000004-0000-4000-8000-000000000004",
            SHARED_TK,
            P4,
            "5ha4ed01-0000-4000-8000-000000000001",
            is_active=False,
        )
        _assign(
            conn,
            "a0000005-0000-4000-8000-000000000005",
            SHARED_TK,
            P4,
            "50100001-0000-4000-8000-000000000002",
            is_active=True,
        )
        conn.commit()
    return scratch_engine


def test_a_shared_agent_becomes_one_copy_per_product(shared_seeded: sa.Engine):
    with shared_seeded.connect() as conn:
        enabled_before = _enabled_pairs(conn, SHARED_TK)

    _upgrade_to_rev()

    with shared_seeded.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT name, product_id FROM agent_templates "
                "WHERE tenant_key = :tk AND deleted_at IS NULL AND role = 'tester' ORDER BY name"
            ),
            {"tk": SHARED_TK},
        ).fetchall()
        by_name = {r[0]: r[1] for r in rows}

        assert by_name["tester"] == P1, "the lowest-UUID owner must keep the original name"
        assert by_name["tester-2"] == P2
        assert by_name["tester-3"] == P3, "a HIDDEN product is still a live product and gets its own copy"
        assert len(by_name) == 3, f"expected exactly three copies, got {sorted(by_name)}"

        for pid in (P1, P2, P3):
            served = conn.execute(
                text(
                    "SELECT t.product_id FROM product_agent_assignments a "
                    "JOIN agent_templates t ON t.id = a.template_id "
                    "WHERE a.product_id = :pid AND a.is_active IS TRUE AND t.role = 'tester'"
                ),
                {"pid": pid},
            ).fetchall()
            assert [r[0] for r in served] == [pid], f"product {pid} must run its OWN tester copy"

        delta_off = conn.execute(
            text(
                "SELECT COUNT(*) FROM product_agent_assignments a "
                "JOIN agent_templates t ON t.id = a.template_id "
                "WHERE a.product_id = :pid AND a.is_active IS FALSE AND t.role = 'tester'"
            ),
            {"pid": P4},
        ).scalar()
        assert delta_off == 0

        enabled_after = _enabled_pairs(conn, SHARED_TK)
        assert (P4, "solo-agent") in enabled_after
        assert (P1, "tester") in enabled_before and (P1, "tester") in enabled_after, (
            "the keeper's name must survive untouched"
        )
        solo_owner = conn.execute(
            text("SELECT product_id FROM agent_templates WHERE tenant_key = :tk AND name = 'solo-agent'"),
            {"tk": SHARED_TK},
        ).scalar()
        assert solo_owner == P4


def test_no_switched_on_row_is_ever_dropped(shared_seeded: sa.Engine):
    with shared_seeded.connect() as conn:
        on_before = conn.execute(
            text(
                "SELECT a.product_id, t.role FROM product_agent_assignments a "
                "JOIN agent_templates t ON t.id = a.template_id "
                "WHERE a.tenant_key = :tk AND a.is_active IS TRUE"
            ),
            {"tk": SHARED_TK},
        ).fetchall()
        on_before_set = {(r[0], r[1]) for r in on_before}

    _upgrade_to_rev()

    with shared_seeded.connect() as conn:
        on_after = conn.execute(
            text(
                "SELECT a.product_id, t.role FROM product_agent_assignments a "
                "JOIN agent_templates t ON t.id = a.template_id "
                "WHERE a.tenant_key = :tk AND a.is_active IS TRUE"
            ),
            {"tk": SHARED_TK},
        ).fetchall()
        on_after_set = {(r[0], r[1]) for r in on_after}

    assert on_before_set == on_after_set, (
        f"switched-ON state changed. lost={sorted(on_before_set - on_after_set)} "
        f"gained={sorted(on_after_set - on_before_set)}"
    )


def test_replay_moves_nothing(shared_seeded: sa.Engine):
    _upgrade_to_rev()

    with shared_seeded.connect() as conn:
        names_once = _names(conn, SHARED_TK)
        enabled_once = _enabled_pairs(conn, SHARED_TK)

    down = _run_alembic("downgrade", _PRE)
    assert down.returncode == 0, f"downgrade failed:\n{down.stdout}\n{down.stderr}"
    _upgrade_to_rev()

    with shared_seeded.connect() as conn:
        assert _names(conn, SHARED_TK) == names_once, "a replay created or renamed agents"
        assert _enabled_pairs(conn, SHARED_TK) == enabled_once, "a replay moved a switch"



CREW_TK = "tk_ce0104_crew"
CP1 = "c1111111-0000-4000-8000-000000000001"
CP2 = "c2222222-0000-4000-8000-000000000002"


@pytest.fixture
def crew_seeded(scratch_engine: sa.Engine):
    _upgrade_to_pre(scratch_engine)
    with scratch_engine.connect() as conn:
        _product(conn, CP1, CREW_TK, "First", is_default=True)
        _product(conn, CP2, CREW_TK, "Second")

        shared = {"implementer": "c8ared01", "tester": "c8ared02", "reviewer": "c8ared03"}
        for role, prefix in shared.items():
            tid = f"{prefix}-0000-4000-8000-000000000001"
            _template(conn, tid, CREW_TK, role, role=role)
            _assign(conn, f"{prefix}-0000-4000-8000-000000000011", CREW_TK, CP1, tid, is_active=True)
            _assign(conn, f"{prefix}-0000-4000-8000-000000000012", CREW_TK, CP2, tid, is_active=True)

        _template(conn, "c0111d3d-0000-4000-8000-000000000001", CREW_TK, "tester-2", role="tester")
        _assign(
            conn,
            "c0111d3d-0000-4000-8000-000000000011",
            CREW_TK,
            CP1,
            "c0111d3d-0000-4000-8000-000000000001",
            is_active=True,
        )
        conn.commit()
    return scratch_engine


def test_one_taken_name_pushes_the_whole_crew_to_the_next_suffix(crew_seeded: sa.Engine):
    _upgrade_to_rev()

    with crew_seeded.connect() as conn:
        second = conn.execute(
            text(
                "SELECT name FROM agent_templates "
                "WHERE tenant_key = :tk AND product_id = :pid AND deleted_at IS NULL ORDER BY name"
            ),
            {"tk": CREW_TK, "pid": CP2},
        ).fetchall()
        names = [r[0] for r in second]

    assert names == ["implementer-3", "reviewer-3", "tester-3"], (
        f"the crew must share ONE suffix past the occupied -2; got {names}"
    )



FX_CREW = ["analyzer", "documenter", "implementer", "reviewer", "tester"]

FX_T1 = "tk_ce0104_fixture_1"
FX_T2 = "tk_ce0104_fixture_2"
FX_T3 = "tk_ce0104_fixture_3"
FX_T4 = "tk_ce0104_fixture_4"

FX_PRODUCTS = [
    (FX_T1, "571459f3-0000-4000-8000-00000000000a", "product-a", True, True),
    (FX_T1, "68be7b26-0000-4000-8000-00000000000b", "tolerance-no-rows-a", True, False),
    (FX_T1, "8af0faba-0000-4000-8000-00000000000c", "hidden-product", False, True),
    (FX_T1, "ab857bf9-0000-4000-8000-00000000000d", "product-b", True, True),
    (FX_T2, "f04037b4-0000-4000-8000-00000000000e", "product-c", True, True),
    (FX_T3, "305fb0d7-0000-4000-8000-00000000000f", "product-d", True, True),
    (FX_T4, "7c3f8b38-0000-4000-8000-000000000010", "tolerance-no-rows-b", True, False),
]


def _effective_roster(conn, product_id: str, tenant_key: str) -> set[str]:
    has_live_opinion = conn.execute(
        text(
            "SELECT 1 FROM product_agent_assignments a JOIN agent_templates t ON t.id = a.template_id "
            "WHERE a.product_id = :pid AND t.deleted_at IS NULL AND t.is_active IS TRUE LIMIT 1"
        ),
        {"pid": product_id},
    ).scalar()

    if has_live_opinion:
        sql = (
            "SELECT t.role FROM product_agent_assignments a JOIN agent_templates t ON t.id = a.template_id "
            "WHERE a.product_id = :pid AND a.is_active IS TRUE AND t.deleted_at IS NULL AND t.is_active IS TRUE"
        )
        params = {"pid": product_id}
    else:
        sql = "SELECT role FROM agent_templates WHERE tenant_key = :tk AND deleted_at IS NULL AND is_active IS TRUE"
        params = {"tk": tenant_key}
    return {r[0] for r in conn.execute(text(sql), params).fetchall()}


def _served_roster(conn, product_id: str) -> set[str]:
    rows = conn.execute(
        text(
            "SELECT t.role FROM product_agent_assignments a JOIN agent_templates t ON t.id = a.template_id "
            "WHERE a.product_id = :pid AND a.is_active IS TRUE AND t.deleted_at IS NULL"
        ),
        {"pid": product_id},
    ).fetchall()
    return {r[0] for r in rows}


@pytest.fixture
def multi_product_account_seeded(scratch_engine: sa.Engine):
    _upgrade_to_pre(scratch_engine)
    with scratch_engine.connect() as conn:
        n = 0
        templates_by_tenant: dict[str, list[str]] = {}
        for tenant in (FX_T1, FX_T2, FX_T3, FX_T4):
            ids = []
            for role in FX_CREW:
                tid = f"9d000104-0000-4000-8000-{n:012d}"
                n += 1
                _template(conn, tid, tenant, role, role=role)
                ids.append(tid)
            templates_by_tenant[tenant] = ids

        a = 0
        for tenant, pid, label, shown, has_rows in FX_PRODUCTS:
            _product(conn, pid, tenant, label, is_active=shown, is_default=pid.startswith("571459f3"))
            if not has_rows:
                continue
            for tid in templates_by_tenant[tenant]:
                _assign(conn, f"9da50104-0000-4000-8000-{a:012d}", tenant, pid, tid, is_active=True)
                a += 1
        conn.commit()
    return scratch_engine


def test_every_product_serves_exactly_what_it_served_before(multi_product_account_seeded: sa.Engine):
    with multi_product_account_seeded.connect() as conn:
        before = {pid: _effective_roster(conn, pid, tk) for tk, pid, _l, _s, _h in FX_PRODUCTS}
        assert all(r == set(FX_CREW) for r in before.values()), f"fixture is wrong: {before}"

    _upgrade_to_rev()

    with multi_product_account_seeded.connect() as conn:
        after = {pid: _served_roster(conn, pid) for _tk, pid, _l, _s, _h in FX_PRODUCTS}

    for _tk, pid, label, _s, _h in FX_PRODUCTS:
        assert after[pid] == before[pid], (
            f"{label} ({pid[:8]}) served {sorted(before[pid])} before and {sorted(after[pid])} after"
        )


def test_tolerance_products_do_not_go_dark(multi_product_account_seeded: sa.Engine):
    tolerance_products = [pid for _tk, pid, _l, _s, has_rows in FX_PRODUCTS if not has_rows]
    assert len(tolerance_products) == 2, "fixture is wrong: the tolerance case must be represented"

    _upgrade_to_rev()

    with multi_product_account_seeded.connect() as conn:
        for pid in tolerance_products:
            assert _served_roster(conn, pid) == set(FX_CREW), (
                f"tolerance product {pid[:8]} went dark: it serves {sorted(_served_roster(conn, pid))}"
            )
            owned = conn.execute(
                text("SELECT COUNT(*) FROM agent_templates WHERE product_id = :pid AND deleted_at IS NULL"),
                {"pid": pid},
            ).scalar()
            assert owned == len(FX_CREW), f"tolerance product {pid[:8]} owns {owned} agents, expected {len(FX_CREW)}"


def test_hidden_product_is_migrated_like_any_other(multi_product_account_seeded: sa.Engine):
    hidden = next(pid for _tk, pid, _l, shown, _h in FX_PRODUCTS if not shown)

    _upgrade_to_rev()

    with multi_product_account_seeded.connect() as conn:
        owned = conn.execute(
            text("SELECT COUNT(*) FROM agent_templates WHERE product_id = :pid AND deleted_at IS NULL"),
            {"pid": hidden},
        ).scalar()
        assert owned == len(FX_CREW), "a hidden product must own its own crew like any other"

        foreign = conn.execute(
            text(
                "SELECT COUNT(*) FROM product_agent_assignments a JOIN agent_templates t ON t.id = a.template_id "
                "WHERE a.product_id = :pid AND t.product_id <> :pid"
            ),
            {"pid": hidden},
        ).scalar()
        assert foreign == 0, "a hidden product must not be left pointing at another product's agents"


def test_copy_and_rename_counts_match_the_expected_shape(multi_product_account_seeded: sa.Engine):
    _upgrade_to_rev()

    with multi_product_account_seeded.connect() as conn:
        t1_total = conn.execute(
            text("SELECT COUNT(*) FROM agent_templates WHERE tenant_key = :tk AND deleted_at IS NULL"),
            {"tk": FX_T1},
        ).scalar()
        assert t1_total == 20, f"5 originals + 15 copies expected for the four-product tenant, got {t1_total}"

        keeper = next(pid for _tk, pid, _l, _s, _h in FX_PRODUCTS if pid.startswith("571459f3"))
        plain = conn.execute(
            text(
                "SELECT name FROM agent_templates WHERE tenant_key = :tk AND product_id = :pid "
                "AND deleted_at IS NULL ORDER BY name"
            ),
            {"tk": FX_T1, "pid": keeper},
        ).fetchall()
        assert [r[0] for r in plain] == sorted(FX_CREW), "the lowest-UUID product keeps the unsuffixed names"

        for suffix, prefix in (("-2", "68be7b26"), ("-3", "8af0faba"), ("-4", "ab857bf9")):
            pid = next(p for _tk, p, _l, _s, _h in FX_PRODUCTS if p.startswith(prefix))
            names = conn.execute(
                text("SELECT name FROM agent_templates WHERE product_id = :pid AND deleted_at IS NULL ORDER BY name"),
                {"pid": pid},
            ).fetchall()
            got = [r[0] for r in names]
            assert got == sorted(f"{r}{suffix}" for r in FX_CREW), (
                f"product {prefix} should hold the crew at {suffix}; got {got}"
            )

        for tenant in (FX_T2, FX_T3, FX_T4):
            names = conn.execute(
                text("SELECT name FROM agent_templates WHERE tenant_key = :tk AND deleted_at IS NULL ORDER BY name"),
                {"tk": tenant},
            ).fetchall()
            assert [r[0] for r in names] == sorted(FX_CREW), (
                f"sole-owner tenant {tenant} should be stamped only, never renamed"
            )



STEP0_TK = "tk_ce0104_step0"
S0_P = "50000000-0000-4000-8000-000000000001"


@pytest.fixture
def step0_seeded(scratch_engine: sa.Engine):
    _upgrade_to_pre(scratch_engine)
    with scratch_engine.connect() as conn:
        _product(conn, S0_P, STEP0_TK, "Only retired rows", is_default=True)

        retired = []
        for n, role in enumerate(("analyzer", "documenter")):
            tid = f"5e000104-0000-4000-8000-{n:012d}"
            _template(conn, tid, STEP0_TK, role, role=role, is_active=False)
            retired.append(tid)
        live = []
        for n, role in enumerate(("implementer", "reviewer", "tester"), start=10):
            tid = f"5e000104-0000-4000-8000-{n:012d}"
            _template(conn, tid, STEP0_TK, role, role=role, is_active=True)
            live.append(tid)

        for n, tid in enumerate(retired):
            _assign(conn, f"5a000104-0000-4000-8000-{n:012d}", STEP0_TK, S0_P, tid, is_active=True)
        conn.commit()
    return scratch_engine


def test_a_product_whose_only_rows_are_retired_is_still_materialised(step0_seeded: sa.Engine):
    with step0_seeded.connect() as conn:
        before = _effective_roster(conn, S0_P, STEP0_TK)
        assert before == {"implementer", "reviewer", "tester"}, (
            f"fixture is wrong: this product should be on the tolerance path, serving the "
            f"tenant-active set. got={sorted(before)}"
        )

    _upgrade_to_rev()

    with step0_seeded.connect() as conn:
        after = _served_roster(conn, S0_P)

    assert before <= after, (
        "a product whose only junction rows point at RETIRED agents was being served the "
        f"tenant-active set, and must keep every one of them. before={sorted(before)} "
        f"after={sorted(after)}"
    )
    assert after == {"implementer", "reviewer", "tester", "analyzer", "documenter"}, (
        "it must ALSO regain the two agents it had switched on that the account-wide "
        f"retire flag was vetoing -- the stuck-seven fix. got={sorted(after)}"
    )


def test_step_0_runs_before_the_retire_flag_is_normalised(step0_seeded: sa.Engine):
    _upgrade_to_rev()

    with step0_seeded.connect() as conn:
        served = _served_roster(conn, S0_P)
        assert served != {"analyzer", "documenter"}, (
            "this product serves ONLY its two retired agents -- the signature of the "
            "retire-flag normalisation having run before step 0, which makes step 0's "
            "tolerance probe read a state that did not exist pre-migration."
        )
        assert {"implementer", "reviewer", "tester"} <= served, (
            f"the tolerance set step 0 exists to write out is missing. got={sorted(served)}"
        )

        owned = conn.execute(
            text("SELECT COUNT(*) FROM agent_templates WHERE product_id = :pid AND deleted_at IS NULL"),
            {"pid": S0_P},
        ).scalar()
        assert owned == 5, f"all five agents must end up owned by this product, got {owned}"



DEGENERATE_TK = "tk_ce0104_degenerate"


@pytest.fixture
def degenerate_seeded(scratch_engine: sa.Engine):
    _upgrade_to_pre(scratch_engine)
    with scratch_engine.connect() as conn:
        for n, role in enumerate(("implementer", "tester")):
            _template(conn, f"de000104-0000-4000-8000-{n:012d}", DEGENERATE_TK, role, role=role)

        trashed_tk = f"{DEGENERATE_TK}_trashed"
        _product(conn, "de111111-0000-4000-8000-000000000001", trashed_tk, "Trashed product")
        conn.execute(
            text("UPDATE products SET deleted_at = NOW() WHERE id = :pid"),
            {"pid": "de111111-0000-4000-8000-000000000001"},
        )
        for n, role in enumerate(("implementer", "tester"), start=20):
            tid = f"de000104-0000-4000-8000-{n:012d}"
            _template(conn, tid, trashed_tk, role, role=role)
            _assign(
                conn,
                f"de000104-0000-4000-8000-{n + 100:012d}",
                trashed_tk,
                "de111111-0000-4000-8000-000000000001",
                tid,
                is_active=True,
            )
        conn.commit()
    return scratch_engine


def test_a_tenant_with_no_live_product_is_left_alone(degenerate_seeded: sa.Engine):
    _upgrade_to_rev()

    with degenerate_seeded.connect() as conn:
        for tenant in (DEGENERATE_TK, f"{DEGENERATE_TK}_trashed"):
            rows = conn.execute(
                text(
                    "SELECT name, product_id FROM agent_templates "
                    "WHERE tenant_key = :tk AND deleted_at IS NULL ORDER BY name"
                ),
                {"tk": tenant},
            ).fetchall()
            assert len(rows) == 2, f"{tenant}: agents were added or removed -- {rows}"
            assert all(r[1] is None for r in rows), (
                f"{tenant}: the migration invented an owner for agents with no live product -- {rows}"
            )


def test_the_degenerate_tenants_do_not_stop_the_rest_of_the_upgrade(degenerate_seeded: sa.Engine):
    with degenerate_seeded.connect() as conn:
        _product(conn, "de222222-0000-4000-8000-000000000001", "tk_ce0104_normal", "Normal product", is_default=True)
        tid = "de000104-0000-4000-8000-000000000900"
        _template(conn, tid, "tk_ce0104_normal", "implementer", role="implementer")
        _assign(
            conn,
            "de000104-0000-4000-8000-000000000901",
            "tk_ce0104_normal",
            "de222222-0000-4000-8000-000000000001",
            tid,
            is_active=True,
        )
        conn.commit()

    _upgrade_to_rev()

    with degenerate_seeded.connect() as conn:
        owner = conn.execute(text("SELECT product_id FROM agent_templates WHERE id = :tid"), {"tid": tid}).scalar()
        assert owner == "de222222-0000-4000-8000-000000000001", (
            "a normal tenant in the same database did not migrate -- a degenerate tenant "
            "earlier in the loop stopped the walk"
        )
