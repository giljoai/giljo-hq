# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))




def _make_installer(**extra_settings):
    from installer.core.database import DatabaseInstaller

    return DatabaseInstaller(
        settings={
            "host": "localhost",
            "port": 5432,
            "password": "pg_admin_pw",
            "username": "postgres",
            "db_name": "giljo_mcp",
            **extra_settings,
        }
    )


def _build_psycopg2_mock(monkeypatch, db_mod, *, db_exists, owner_exists, user_exists):
    import psycopg2.sql as real_sql

    captured_templates: list[str] = []

    def spy_sql(template: str):
        captured_templates.append(template)
        return real_sql.SQL(template)

    monkeypatch.setattr(
        db_mod,
        "sql",
        types.SimpleNamespace(SQL=spy_sql, Identifier=real_sql.Identifier),
    )

    _admin_responses = iter(
        [
            (1,) if db_exists else None,
            (1,) if owner_exists else None,
            (1,) if user_exists else None,
        ]
    )
    admin_cursor = MagicMock()
    admin_cursor.fetchone.side_effect = lambda: next(_admin_responses)
    admin_cursor_ctx = MagicMock()
    admin_cursor_ctx.__enter__ = MagicMock(return_value=admin_cursor)
    admin_cursor_ctx.__exit__ = MagicMock(return_value=False)

    admin_conn = MagicMock()
    admin_conn.cursor.return_value = admin_cursor_ctx
    admin_conn.set_isolation_level = MagicMock()
    admin_conn.close = MagicMock()

    db_cursor = MagicMock()
    db_cursor_ctx = MagicMock()
    db_cursor_ctx.__enter__ = MagicMock(return_value=db_cursor)
    db_cursor_ctx.__exit__ = MagicMock(return_value=False)

    db_conn = MagicMock()
    db_conn.cursor.return_value = db_cursor_ctx
    db_conn.set_isolation_level = MagicMock()
    db_conn.close = MagicMock()

    _connect_calls = iter([admin_conn, db_conn])

    mock_pg = MagicMock()
    mock_pg.connect.side_effect = lambda **kw: next(_connect_calls)
    mock_pg.OperationalError = Exception
    mock_pg.Error = Exception
    monkeypatch.setattr(db_mod, "psycopg2", mock_pg)

    return admin_cursor, db_cursor, captured_templates




def test_create_database_direct_no_alter_role_when_both_roles_exist(monkeypatch, tmp_path):
    import installer.core.database as db_mod

    _, _, captured_templates = _build_psycopg2_mock(
        monkeypatch, db_mod, db_exists=True, owner_exists=True, user_exists=True
    )

    inst = _make_installer()
    monkeypatch.setattr(inst, "save_credentials", lambda: None)

    result = inst.create_database_direct()

    assert result.get("success") is True, f"Expected success; got: {result}"
    assert result.get("roles_reused") is True, (
        "Expected roles_reused=True when both giljo_owner and giljo_user already exist"
    )

    forbidden = [
        t for t in captured_templates if "ALTER" in t.upper() and "ROLE" in t.upper() and "PASSWORD" in t.upper()
    ]
    assert not forbidden, (
        f"ALTER ROLE PASSWORD must never be issued for existing roles; offending sql.SQL() templates: {forbidden}"
    )


@pytest.mark.parametrize(
    "owner_exists,user_exists,present,missing",
    [
        (True, False, "giljo_owner", "giljo_user"),
        (False, True, "giljo_user", "giljo_owner"),
    ],
)
def test_create_database_direct_fails_fast_on_partial_role_state(
    monkeypatch, tmp_path, owner_exists, user_exists, present, missing
):
    import installer.core.database as db_mod

    _, _, captured_templates = _build_psycopg2_mock(
        monkeypatch, db_mod, db_exists=False, owner_exists=owner_exists, user_exists=user_exists
    )

    inst = _make_installer()
    save_spy = MagicMock()
    monkeypatch.setattr(inst, "save_credentials", save_spy)

    result = inst.create_database_direct()

    assert result.get("success") is False, f"Partial role state must not succeed; got: {result}"
    assert result.get("partial_roles") is True, "Expected partial_roles=True marker on the mixed-state abort"

    errors = " ".join(result.get("errors", []))
    assert present in errors and missing in errors, f"Error must name both roles; got: {result.get('errors')}"
    assert "DROP ROLE" in errors, f"Error must give an actionable recovery command; got: {result.get('errors')}"

    role_mutations = [
        t for t in captured_templates if ("CREATE" in t.upper() or "ALTER" in t.upper()) and "ROLE" in t.upper()
    ]
    assert not role_mutations, (
        f"No role must be created or altered in the partial state (would mismatch .env); got: {role_mutations}"
    )
    save_spy.assert_not_called()


def test_create_database_direct_fresh_install_creates_roles(monkeypatch, tmp_path):
    import installer.core.database as db_mod

    _, _, captured_templates = _build_psycopg2_mock(
        monkeypatch, db_mod, db_exists=False, owner_exists=False, user_exists=False
    )

    inst = _make_installer()
    monkeypatch.setattr(inst, "save_credentials", lambda: None)

    result = inst.create_database_direct()

    assert result.get("success") is True, f"Expected success; got: {result}"
    assert result.get("roles_reused") is False, (
        "Expected roles_reused=False on a fresh install with no pre-existing roles"
    )

    create_templates = [t for t in captured_templates if "CREATE" in t.upper() and "ROLE" in t.upper()]
    assert len(create_templates) == 2, (  # noqa: PLR2004
        f"Expected exactly 2 CREATE ROLE templates (owner + user); got: {create_templates}"
    )




@pytest.mark.parametrize(
    "flag,value",
    [("headless", True), ("unattended", True)],
)
def test_fallback_setup_no_input_in_non_interactive_mode(monkeypatch, tmp_path, flag, value):
    import platform as plat_mod

    inst = _make_installer(**{flag: value})

    def forbidden_input(prompt=""):
        raise AssertionError(f"input() must not be called when {flag}={value}; got prompt={prompt!r}")

    monkeypatch.setattr("builtins.input", forbidden_input)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(plat_mod, "system", lambda: "Linux")

    monkeypatch.setattr(inst, "save_credentials", lambda: None)
    monkeypatch.setattr(inst, "display_elevation_guide", lambda p: None)
    monkeypatch.setattr(inst, "verify_database_exists", lambda: True)

    dummy_script = tmp_path / "create_db.sh"
    dummy_script.touch()
    monkeypatch.setattr(inst, "generate_unix_script", lambda sd: dummy_script)

    result = inst.fallback_setup()

    assert result.get("success") is True, f"Expected fallback_setup to succeed in {flag}={value} mode; got: {result}"




def test_generate_windows_script_no_alter_role(tmp_path):
    from installer.core.database import DatabaseInstaller

    inst = DatabaseInstaller(
        settings={"host": "localhost", "port": 5432, "password": "pw", "username": "postgres", "db_name": "giljo_mcp"}
    )
    inst.owner_password = "ownerpass123"
    inst.user_password = "userpass456"

    script_path = inst.generate_windows_script(tmp_path)
    content = script_path.read_text(encoding="utf-8")

    assert "pg_roles" in content, "pg_roles existence check must be present in generated Windows script"
    assert "ALTER ROLE" not in content, (
        "ALTER ROLE must not appear in generated Windows script; "
        "existing roles must have their passwords left unchanged (INF-6260)"
    )


def test_generate_unix_script_no_alter_role(tmp_path):
    from installer.core.database import DatabaseInstaller

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    inst = DatabaseInstaller(
        settings={"host": "localhost", "port": 5432, "password": "pw", "username": "postgres", "db_name": "giljo_mcp"}
    )
    inst.owner_password = "ownerpass123"
    inst.user_password = "userpass456"

    script_path = inst.generate_unix_script(scripts_dir)
    content = script_path.read_text(encoding="utf-8")

    assert "pg_roles" in content, "pg_roles existence check must be present in generated Unix script"
    assert "ALTER ROLE" not in content, (
        "ALTER ROLE must not appear in generated Unix script; "
        "existing roles must have their passwords left unchanged (INF-6260)"
    )
