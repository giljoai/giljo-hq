# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SEC-9572 -- the shared secret files must survive a multi-worker boot race.

``uvicorn --workers N`` boots N processes against one home directory, so more
than one process can reach a shared secret file while another is still
establishing it.

The invariant these tests pin: a partially-written secret file must never be
accepted. Both the encryption key and the JWT secret are read through a retry
that requires a complete, valid payload before use, and exactly one process
is the creator.

The reads here are driven through the retry loop's own wait rather than through
real timing, so the interleaving is exact instead of probabilistic.
"""

import threading

import pytest
from cryptography.fernet import Fernet

from giljo_mcp import secret_files as secret_files_module
from giljo_mcp.auth_manager import AuthManager


class _WaitThatFillsTheFile:
    """Stands in for the retry loop's wait: the winner's bytes land during it."""

    def __init__(self, path, payload):
        self._path = path
        self._payload = payload
        self.waits = 0

    def sleep(self, _seconds):
        self.waits += 1
        self._path.write_bytes(self._payload)


@pytest.fixture
def giljo_home(tmp_path, monkeypatch):
    """An isolated ~/.giljo-mcp for one test (no module-level state, xdist-safe)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("GILJO_MCP_ENCRYPTION_KEY", raising=False)
    home = tmp_path / ".giljo-mcp"
    home.mkdir()
    return home


def _auth_manager():
    """AuthManager with the JWT secret pinned, so only the key path is under test."""
    return AuthManager(config=object())


def test_torn_encryption_key_read_retries_instead_of_killing_the_worker(giljo_home, monkeypatch):
    """A key file the creator has not yet filled must be waited out, not consumed."""
    monkeypatch.setenv("JWT_SECRET", "jwt-secret-not-under-test")
    key_file = giljo_home / "encryption_key"
    key_file.write_bytes(b"")  # created by the winner; its bytes have not landed yet
    winning_key = Fernet.generate_key()
    waiter = _WaitThatFillsTheFile(key_file, winning_key)
    monkeypatch.setattr(secret_files_module, "time", waiter)

    manager = _auth_manager()

    assert manager.encryption_key == winning_key
    assert waiter.waits == 1, "should have waited exactly once for the winner"


def test_torn_jwt_secret_read_waits_for_the_complete_payload(giljo_home, monkeypatch):
    """The JWT secret is held to the same rule: only a complete payload is used."""
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("GILJO_MCP_SECRET_KEY", raising=False)
    secret_file = giljo_home / "jwt_secret"
    secret_file.write_bytes(b"")
    waiter = _WaitThatFillsTheFile(secret_file, b"the-winners-secret")
    monkeypatch.setattr(secret_files_module, "time", waiter)

    manager = _auth_manager()

    assert manager.jwt_secret == "the-winners-secret"


def test_racing_workers_all_end_up_on_the_same_key(giljo_home, monkeypatch):
    """O_CREAT|O_EXCL picks ONE creator, so every process agrees on one key."""
    monkeypatch.setenv("JWT_SECRET", "jwt-secret-not-under-test")
    start = threading.Barrier(8)
    keys = []
    lock = threading.Lock()

    def _boot():
        start.wait()
        key = _auth_manager().encryption_key
        with lock:
            keys.append(key)

    threads = [threading.Thread(target=_boot) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(keys) == 8
    assert len(set(keys)) == 1, "workers disagreed on the encryption key"
    assert keys[0] == (giljo_home / "encryption_key").read_bytes()


def test_permanently_unreadable_key_file_fails_loudly_and_names_itself(giljo_home, monkeypatch):
    """A key file that never becomes readable must say so, not raise a bare crypto error."""
    monkeypatch.setenv("JWT_SECRET", "jwt-secret-not-under-test")
    key_file = giljo_home / "encryption_key"
    key_file.write_bytes(b"")
    monkeypatch.setattr(secret_files_module, "SECRET_FILE_RETRY_DELAY_SECONDS", 0)

    with pytest.raises(RuntimeError) as excinfo:
        _auth_manager()

    message = str(excinfo.value)
    assert str(key_file) in message
    assert "Delete the file" in message


def test_malformed_encryption_key_env_var_names_the_variable(giljo_home, monkeypatch):
    """A bad GILJO_MCP_ENCRYPTION_KEY must name itself, not just fail Fernet's shape check."""
    monkeypatch.setenv("JWT_SECRET", "jwt-secret-not-under-test")
    monkeypatch.setenv("GILJO_MCP_ENCRYPTION_KEY", "openssl-rand-hex-32-is-not-a-fernet-key")

    with pytest.raises(ValueError) as excinfo:
        _auth_manager()

    message = str(excinfo.value)
    assert "GILJO_MCP_ENCRYPTION_KEY" in message
    assert "Fernet.generate_key" in message


def test_valid_encryption_key_env_var_is_still_used_verbatim(giljo_home, monkeypatch):
    """The env-var branch keeps working -- the new check must not reject a good key."""
    monkeypatch.setenv("JWT_SECRET", "jwt-secret-not-under-test")
    good_key = Fernet.generate_key()
    monkeypatch.setenv("GILJO_MCP_ENCRYPTION_KEY", good_key.decode())

    assert _auth_manager().encryption_key == good_key
    assert not (giljo_home / "encryption_key").exists()
