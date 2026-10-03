# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_PY = REPO_ROOT / "install.py"

_UNATTENDED_ENV_KEYS = (
    "GILJO_UNATTENDED",
    "GILJO_PG_PASSWORD",
    "GILJO_NETWORK_MODE",
    "GILJO_DB_NAME",
    "GILJO_INSTALL_DIR",
)


def _run_install(env_extra: dict, args=("--setup-only",), cwd=None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    for key in _UNATTENDED_ENV_KEYS:
        env.pop(key, None)
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(INSTALL_PY), *args],
        cwd=str(cwd or REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def test_unattended_requires_pg_password(tmp_path):
    result = _run_install(
        {
            "GILJO_UNATTENDED": "1",
            "GILJO_NETWORK_MODE": "localhost",
            "GILJO_INSTALL_DIR": str(tmp_path),
        },
        cwd=tmp_path,
    )
    assert result.returncode == 1, (
        f"expected exit 1, got {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "PostgreSQL password" in combined, combined


def _import_installer(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    import install  # noqa: PLC0415  # reason: deferred import keeps module side effects inside the test

    monkeypatch.setattr(
        install.UnifiedInstaller,
        "_set_postgres_password_via_peer",
        lambda self, password: True,
    )
    for key in _UNATTENDED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return install


def test_unattended_localhost_binds_loopback(tmp_path, monkeypatch):
    install = _import_installer(monkeypatch, tmp_path)
    monkeypatch.setenv("GILJO_UNATTENDED", "1")
    monkeypatch.setenv("GILJO_PG_PASSWORD", "testpw")
    monkeypatch.setenv("GILJO_NETWORK_MODE", "localhost")

    inst = install.UnifiedInstaller(
        settings={"unattended": True, "pg_password": "testpw", "install_dir": str(tmp_path)}
    )
    inst._apply_unattended_settings()

    assert inst.settings["bind"] == "127.0.0.1"
    assert inst.settings["network_mode"] == "localhost"
    assert inst.settings["db_name"] == "giljo_mcp"


def test_unattended_lan_binds_all_interfaces(tmp_path, monkeypatch):
    install = _import_installer(monkeypatch, tmp_path)
    monkeypatch.setenv("GILJO_UNATTENDED", "1")
    monkeypatch.setenv("GILJO_PG_PASSWORD", "testpw")
    monkeypatch.setenv("GILJO_NETWORK_MODE", "lan")
    monkeypatch.setenv("GILJO_DB_NAME", "giljo_lan_test")

    inst = install.UnifiedInstaller(
        settings={"unattended": True, "pg_password": "testpw", "install_dir": str(tmp_path)}
    )
    inst._apply_unattended_settings()

    assert inst.settings["bind"] == "0.0.0.0"
    assert inst.settings["network_mode"] != "localhost"
    assert inst.settings["db_name"] == "giljo_lan_test"


def test_unattended_lan_http_skips_ssl(tmp_path, monkeypatch):
    install = _import_installer(monkeypatch, tmp_path)
    monkeypatch.setenv("GILJO_UNATTENDED", "1")
    monkeypatch.setenv("GILJO_PG_PASSWORD", "testpw")
    monkeypatch.setenv("GILJO_NETWORK_MODE", "lan")

    inst = install.UnifiedInstaller(
        settings={"unattended": True, "pg_password": "testpw", "install_dir": str(tmp_path)}
    )
    inst._apply_unattended_settings()

    assert inst.settings["bind"] == "0.0.0.0"
    assert inst.settings["network_mode"] != "localhost"
    assert "ssl_enabled" not in inst.settings
    assert "ssl_opt_out" not in inst.settings


def test_unattended_force_http_opts_out_on_lan(tmp_path, monkeypatch):
    install = _import_installer(monkeypatch, tmp_path)
    monkeypatch.setenv("GILJO_UNATTENDED", "1")
    monkeypatch.setenv("GILJO_PG_PASSWORD", "testpw")
    monkeypatch.setenv("GILJO_NETWORK_MODE", "lan")

    inst = install.UnifiedInstaller(
        settings={"unattended": True, "pg_password": "testpw", "install_dir": str(tmp_path)}
    )
    inst._apply_unattended_settings()

    assert inst.settings["bind"] == "0.0.0.0"
    assert "ssl_enabled" not in inst.settings
    assert "ssl_opt_out" not in inst.settings


def test_unattended_bare_lan_configures_http(tmp_path, monkeypatch):
    install = _import_installer(monkeypatch, tmp_path)
    monkeypatch.setenv("GILJO_UNATTENDED", "1")
    monkeypatch.setenv("GILJO_PG_PASSWORD", "testpw")
    monkeypatch.setenv("GILJO_NETWORK_MODE", "lan")
    monkeypatch.delenv("GILJO_FORCE_HTTP", raising=False)

    inst = install.UnifiedInstaller(
        settings={"unattended": True, "pg_password": "testpw", "install_dir": str(tmp_path)}
    )
    inst._apply_unattended_settings()

    assert inst.settings["bind"] == "0.0.0.0"
    assert "ssl_enabled" not in inst.settings
    assert "ssl_opt_out" not in inst.settings


def test_is_private_lan_host_classifier():
    from installer.shared.network import is_private_lan_host

    assert is_private_lan_host("192.0.2.10") is True
    assert is_private_lan_host("198.51.100.7") is True
    assert is_private_lan_host("203.0.113.9") is True
    assert is_private_lan_host("127.0.0.1") is True
    assert is_private_lan_host("169.254.1.1") is True
    assert is_private_lan_host("8.8.8.8") is False
    assert is_private_lan_host("example.com") is False
    assert is_private_lan_host("mybox.local") is False


def test_unattended_missing_password_raises_in_process(tmp_path, monkeypatch):
    install = _import_installer(monkeypatch, tmp_path)
    monkeypatch.setenv("GILJO_UNATTENDED", "1")
    monkeypatch.setenv("GILJO_NETWORK_MODE", "localhost")

    inst = install.UnifiedInstaller(settings={"unattended": True, "install_dir": str(tmp_path)})
    inst.settings["pg_password"] = None
    with pytest.raises(ValueError, match="PostgreSQL password"):
        inst._apply_unattended_settings()



_PUBLIC_ADAPTER = [{"ip": "8.8.8.8", "name": "eth0", "is_virtual": False}]


def _abort_getpass(prompt: str = "") -> str:
    raise KeyboardInterrupt("abort PG section in test")


@pytest.mark.parametrize(
    "mode,expected_bind",
    [
        ("localhost", "127.0.0.1"),
        ("lan", "0.0.0.0"),
        ("wan", "0.0.0.0"),
    ],
)
def test_unattended_always_configures_http(tmp_path, monkeypatch, mode, expected_bind):
    install = _import_installer(monkeypatch, tmp_path)
    monkeypatch.setenv("GILJO_UNATTENDED", "1")
    monkeypatch.setenv("GILJO_PG_PASSWORD", "testpw")
    monkeypatch.setenv("GILJO_NETWORK_MODE", mode)

    inst = install.UnifiedInstaller(
        settings={"unattended": True, "pg_password": "testpw", "install_dir": str(tmp_path)}
    )
    inst._apply_unattended_settings()

    assert inst.settings["bind"] == expected_bind
    assert "ssl_enabled" not in inst.settings
    assert "ssl_opt_out" not in inst.settings


def test_unattended_wan_warns_but_does_not_fail(tmp_path, monkeypatch, capsys):
    install = _import_installer(monkeypatch, tmp_path)
    monkeypatch.setenv("GILJO_UNATTENDED", "1")
    monkeypatch.setenv("GILJO_PG_PASSWORD", "testpw")
    monkeypatch.setenv("GILJO_NETWORK_MODE", "wan")

    inst = install.UnifiedInstaller(
        settings={"unattended": True, "pg_password": "testpw", "install_dir": str(tmp_path)}
    )
    inst._apply_unattended_settings()

    assert "ssl_enabled" not in inst.settings
    combined = " ".join(capsys.readouterr()).lower()
    assert "cleartext" in combined or "reverse proxy" in combined or "tunnel" in combined, (
        f"expected a cleartext/WAN warning in output; got: {combined!r}"
    )


def test_interactive_autodetect_public_ip_warns_no_fail(tmp_path, monkeypatch, capsys):
    import installer.shared.network as net_mod

    install = _import_installer(monkeypatch, tmp_path)
    monkeypatch.setattr(net_mod, "get_network_adapters", lambda: _PUBLIC_ADAPTER)

    tty_calls = iter(["2"])
    monkeypatch.setattr(install, "tty_input", lambda prompt="": next(tty_calls))
    monkeypatch.setattr(install, "getpass_with_asterisks", _abort_getpass)

    inst = install.UnifiedInstaller(settings={"install_dir": str(tmp_path)})
    with pytest.raises(KeyboardInterrupt):
        inst.ask_installation_questions()

    assert "ssl_opt_out" not in inst.settings, (
        "public IP auto-detect (choice 2) must not set ssl_opt_out (removed concept)"
    )
    assert "ssl_enabled" not in inst.settings
    combined = " ".join(capsys.readouterr()).lower()
    assert "cleartext" in combined or "reverse proxy" in combined or "tunnel" in combined, (
        f"expected a WAN cleartext warning in output; got: {combined!r}"
    )


def test_interactive_specific_adapter_public_ip_warns_no_fail(tmp_path, monkeypatch, capsys):
    import installer.shared.network as net_mod

    install = _import_installer(monkeypatch, tmp_path)
    monkeypatch.setattr(net_mod, "get_network_adapters", lambda: _PUBLIC_ADAPTER)

    tty_calls = iter(["3"])
    monkeypatch.setattr(install, "tty_input", lambda prompt="": next(tty_calls))
    monkeypatch.setattr(install, "getpass_with_asterisks", _abort_getpass)

    inst = install.UnifiedInstaller(settings={"install_dir": str(tmp_path)})
    with pytest.raises(KeyboardInterrupt):
        inst.ask_installation_questions()

    assert "ssl_opt_out" not in inst.settings, (
        "public IP specific-adapter (choice 3) must not set ssl_opt_out (removed concept)"
    )
    assert "ssl_enabled" not in inst.settings
    combined = " ".join(capsys.readouterr()).lower()
    assert "cleartext" in combined or "reverse proxy" in combined or "tunnel" in combined, (
        f"expected a WAN cleartext warning in output; got: {combined!r}"
    )
