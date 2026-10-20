# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ast
import re
from pathlib import Path

import bcrypt
import pytest

from giljo_mcp.utils import password_helper
from giljo_mcp.utils.password_helper import BCRYPT_MAX_PASSWORD_BYTES, async_hash_password, async_verify_password


REPO_ROOT = Path(__file__).resolve().parents[2]

EXACT_72_BYTES = "x" * 72

FIXTURE_HASHES = {
    "correct horse battery staple": "$2b$12$ZJhaqeWjDpPH8rEQX5bUbePZaL/Bxd2k9M6zkjTcHgbp6K0GzwJsm",
    "pässwörd✓": "$2b$12$WlljgB.ibz/WSbe0G6HobeSDACd.8LM1.GVE./YXIVwT8Am6b/MU.",
    "4821": "$2b$12$fRlLpg7zIFic8yDpzJQRI..ik4lds9m..6Avy4v1IbUTVwgSm1rS2",
    EXACT_72_BYTES: "$2b$12$csrR5Stzc3iO.eOd.MKnG.smN6PqiPzZEKneOuDzZJUvMdTZlKOr6",
}
FIXTURE_IDS = ["ascii", "utf8-multibyte", "pin", "exactly-72-bytes"]

PREFIX_MATCH_73_BYTES = EXACT_72_BYTES + "x"
MULTIBYTE_73_BYTES = "Aa1!" + "ä" * 34 + "x"


def test_fixture_byte_math():
    assert len(EXACT_72_BYTES.encode("utf-8")) == BCRYPT_MAX_PASSWORD_BYTES
    assert len(PREFIX_MATCH_73_BYTES.encode("utf-8")) == 73
    assert len(MULTIBYTE_73_BYTES) == 39 and len(MULTIBYTE_73_BYTES.encode("utf-8")) == 73
    assert len("pässwörd✓".encode()) == 13




def test_installed_bcrypt_is_major_5():
    assert bcrypt.__version__.startswith("5."), bcrypt.__version__


@pytest.mark.parametrize("manifest", ["requirements.txt", "pyproject.toml"])
def test_declared_bcrypt_floor_is_5(manifest):
    text = (REPO_ROOT / manifest).read_text(encoding="utf-8")
    floors = re.findall(r"""^\s*"?bcrypt>=([0-9.]+)""", text, flags=re.MULTILINE)
    assert floors == ["5.0.0"], f"{manifest}: bcrypt floors {floors}"




@pytest.mark.asyncio
@pytest.mark.parametrize(("plaintext", "stored_hash"), list(FIXTURE_HASHES.items()), ids=FIXTURE_IDS)
async def test_bcrypt4_hash_verifies_under_bcrypt5(plaintext, stored_hash):
    assert await async_verify_password(plaintext, stored_hash) is True
    assert await async_verify_password(plaintext[:-1] + "!", stored_hash) is False




@pytest.mark.asyncio
@pytest.mark.parametrize("plaintext", [PREFIX_MATCH_73_BYTES, MULTIBYTE_73_BYTES], ids=["ascii-73", "multibyte-73"])
async def test_73_byte_verify_returns_false_without_reaching_checkpw(plaintext, monkeypatch):
    calls = []
    monkeypatch.setattr(password_helper.bcrypt, "checkpw", lambda *a: calls.append(a) or True)

    assert await async_verify_password(plaintext, FIXTURE_HASHES[EXACT_72_BYTES]) is False
    assert calls == []


def test_bcrypt5_itself_refuses_73_bytes():
    with pytest.raises(ValueError, match="72 bytes"):
        bcrypt.checkpw(PREFIX_MATCH_73_BYTES.encode("utf-8"), FIXTURE_HASHES[EXACT_72_BYTES].encode("utf-8"))


@pytest.mark.asyncio
async def test_hash_helper_does_not_truncate_73_bytes():
    with pytest.raises(ValueError, match="72 bytes"):
        await async_hash_password(PREFIX_MATCH_73_BYTES)



KNOWN_HASH_CALL_SITES = {
    ("src/giljo_mcp/utils/password_helper.py", "async_hash_password"): "the helper itself",
    ("src/giljo_mcp/services/auth_service.py", "_register_user_impl"): "RegisterUserRequest.password BoundedPassword",
    ("src/giljo_mcp/services/auth_service.py", "_create_first_admin_impl"): (
        "RegisterUserRequest.password BoundedPassword; SaaS CLI bootstrap prints bcrypt's ValueError, exit 2"
    ),
    (
        "src/giljo_mcp/services/user_auth_service.py",
        "_change_password_impl",
    ): "PasswordChange.new_password BoundedPassword",
    ("src/giljo_mcp/services/user_auth_service.py", "_set_initial_password_impl"): (
        "SetInitialPasswordRequest.new_password validate_password_strength"
    ),
    ("src/giljo_mcp/services/user_auth_service.py", "reset_password_via_pin"): (
        "PinPasswordResetRequest.new_password validate_password_strength"
    ),
    ("src/giljo_mcp/services/user_service.py", "_create_user_impl"): "UserCreate.password BoundedPassword",
    ("src/giljo_mcp/services/user_service.py", "_update_user_impl"): "UserUpdate.password BoundedPassword",
    ("src/giljo_mcp/services/user_service.py", "set_recovery_pin"): "UserUpdate.recovery_pin ^[0-9]{4}$",
    ("api/endpoints/auth/registration.py", "create_first_admin_user"): "RegisterUserRequest.recovery_pin ^[0-9]{4}$",
    ("api/endpoints/auth_pin_recovery.py", "complete_first_login"): (
        "CompleteFirstLoginRequest validate_password_strength + recovery_pin ^[0-9]{4}$"
    ),
    ("api/saas_endpoints/password_reset.py", "confirm_reset"): "PasswordResetConfirm.new_password BoundedPassword",
    ("src/giljo_mcp/saas/provisioning/service.py", "provision_tenant"): "server-generated 16-char ASCII password",
    ("src/giljo_mcp/saas/auth/oauth_client.py", "register"): "server-generated OAuth client secret",
}


def _is_bcrypt_hashpw(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "hashpw"
        and isinstance(node.value, ast.Name)
        and node.value.id == "bcrypt"
    )


def _hash_call_sites() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for base in ("src/giljo_mcp", "api"):
        for path in sorted((REPO_ROOT / base).rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for func in ast.walk(tree):
                if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for call in ast.walk(func):
                    if not isinstance(call, ast.Call):
                        continue
                    targets = [call.func, *call.args]
                    if any(_is_bcrypt_hashpw(t) for t in targets) or (
                        isinstance(call.func, ast.Name) and call.func.id == "async_hash_password"
                    ):
                        found.add((rel, func.name))
    return found


def test_every_hash_call_site_has_a_named_boundary_cap():
    unknown = _hash_call_sites() - KNOWN_HASH_CALL_SITES.keys()
    assert not unknown, f"bcrypt hash call sites with no recorded 72-byte boundary cap: {sorted(unknown)}"
