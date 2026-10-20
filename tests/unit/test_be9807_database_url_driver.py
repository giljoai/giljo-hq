# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from giljo_mcp.database import DatabaseManager
from giljo_mcp.db_url import normalize_database_url


REPO_ROOT = Path(__file__).resolve().parents[2]
BARE = "postgresql://giljo:s3cret@localhost:5432/giljo_be9807"


@pytest.mark.parametrize(
    ("url", "driver", "expected"),
    [
        (BARE, "sync", "postgresql+psycopg2://giljo:s3cret@localhost:5432/giljo_be9807"),
        (BARE, "async", "postgresql+asyncpg://giljo:s3cret@localhost:5432/giljo_be9807"),
        ("postgres://u:p@h:5432/d", "sync", "postgresql+psycopg2://u:p@h:5432/d"),
        ("postgres://u:p@h:5432/d", "async", "postgresql+asyncpg://u:p@h:5432/d"),
        ("postgresql+asyncpg://u:p@h/d", "sync", "postgresql+psycopg2://u:p@h/d"),
        ("postgresql+psycopg2://u:p@h/d", "async", "postgresql+asyncpg://u:p@h/d"),
        ("postgresql+psycopg2://u:p@h/d", "sync", "postgresql+psycopg2://u:p@h/d"),
        ("postgresql+asyncpg://u:p@h/d", "async", "postgresql+asyncpg://u:p@h/d"),
        ("postgresql+psycopg://u:p@h/d", "sync", "postgresql+psycopg://u:p@h/d"),
        ("sqlite://", "sync", "sqlite://"),
        ("", "sync", ""),
        ("POSTGRESQL://u:p@h/d", "sync", "postgresql+psycopg2://u:p@h/d"),
    ],
)
def test_normalizer_sets_the_scheme(url, driver, expected):
    assert normalize_database_url(url, driver) == expected


def test_normalizer_keeps_credentials_and_query_byte_for_byte():
    tail = "us%40er:p%40ss%2Fw%3Ard%25%3A%2F%2F@db.example:6543/giljo?sslmode=require&options=-csearch_path%3Dx"
    assert normalize_database_url(f"postgresql://{tail}", "sync") == f"postgresql+psycopg2://{tail}"
    assert normalize_database_url(f"postgresql://{tail}", "async") == f"postgresql+asyncpg://{tail}"


def test_normalizer_only_reads_the_first_scheme_separator():
    url = "postgresql://u:a://b@h/d"
    assert normalize_database_url(url, "sync") == "postgresql+psycopg2://u:a://b@h/d"


def test_normalizer_rejects_an_unknown_driver_side():
    with pytest.raises(ValueError, match="sync' or 'async"):
        normalize_database_url(BARE, "psycopg")


@pytest.mark.parametrize("use_null_pool", [False, True])
def test_sync_engine_from_a_bare_url_uses_psycopg2(use_null_pool):
    manager = DatabaseManager(BARE, is_async=False, use_null_pool=use_null_pool)
    try:
        assert manager.engine.url.drivername == "postgresql+psycopg2"
        assert manager.engine.dialect.driver == "psycopg2"
    finally:
        manager.engine.dispose()


@pytest.mark.parametrize("use_null_pool", [False, True])
def test_async_engine_from_a_bare_url_uses_asyncpg(use_null_pool):
    manager = DatabaseManager(BARE, is_async=True, use_null_pool=use_null_pool)
    assert manager.async_engine.url.drivername == "postgresql+asyncpg"
    assert manager.async_engine.dialect.driver == "asyncpg"
    assert manager.database_url == BARE, "the stored URL stays as the user wrote it"


def test_migration_check_opens_its_engine_on_psycopg2(monkeypatch):
    import sqlalchemy
    from sqlalchemy.exc import SQLAlchemyError

    from api.startup.migration_check import get_pending_migration_info

    seen: list[str] = []

    def _record(url, *args, **kwargs):
        seen.append(str(url))
        raise SQLAlchemyError("stop before connecting")

    monkeypatch.setattr(sqlalchemy, "create_engine", _record)
    state = SimpleNamespace(db_manager=SimpleNamespace(database_url=BARE))
    assert get_pending_migration_info(state) == {"unknown": True}
    assert seen == ["postgresql+psycopg2://giljo:s3cret@localhost:5432/giljo_be9807"]


def test_startup_database_url_is_pinned_to_psycopg2(monkeypatch):
    from startup_support.migration_stamp import _get_database_url

    monkeypatch.setenv("DATABASE_URL", BARE)
    assert _get_database_url() == "postgresql+psycopg2://giljo:s3cret@localhost:5432/giljo_be9807"



_ENGINE_OPENERS = {"create_engine", "create_async_engine", "engine_from_config"}
_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "frontend",
    "tests",
    "_historical",
    "archive",
    "WASTE_AUDIT_2026-07",
    "giljo_mcp.egg-info",
    "__pycache__",
}
_PINNED_UPSTREAM = {
    "startup.py": "takes its URL from startup_support.migration_stamp._get_database_url, which normalises",
}
_EXPLICIT_SCHEMES = ("postgresql+psycopg2", "postgresql+asyncpg")


def _opener_modules() -> list[Path]:
    found = []
    for path in REPO_ROOT.rglob("*.py"):
        rel_parts = path.relative_to(REPO_ROOT).parts
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        if not any(name in source for name in _ENGINE_OPENERS):
            continue
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name in _ENGINE_OPENERS and not _literal_explicit_url(node):
                    found.append(path)
                    break
    return found


def _literal_explicit_url(call: ast.Call) -> bool:
    if not call.args or not isinstance(call.args[0], ast.Constant) or not isinstance(call.args[0].value, str):
        return False
    return call.args[0].value.startswith(("sqlite", "postgresql+"))


def _names_an_explicit_driver(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith(_EXPLICIT_SCHEMES):
            return True
    return False


def test_every_engine_opener_pins_its_driver():
    offenders = []
    for path in _opener_modules():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in _PINNED_UPSTREAM:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        if "normalize_database_url" not in source and not _names_an_explicit_driver(source):
            offenders.append(rel)
    assert not offenders, (
        "these modules open a SQLAlchemy engine without giljo_mcp.db_url.normalize_database_url; "
        f"on SQLAlchemy 2.1 a bare postgresql:// URL would load psycopg 3: {sorted(offenders)}"
    )


def test_the_ratchet_sees_the_known_openers():
    rels = {p.relative_to(REPO_ROOT).as_posix() for p in _opener_modules()}
    assert "src/giljo_mcp/database.py" in rels
    assert "migrations/env.py" in rels
    assert "api/startup/migration_check.py" in rels
