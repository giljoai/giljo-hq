# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import os

import startup


def _parse_env(path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


_LAN_CONFIG = """\
version: "3.0.0"
services:
  api:
    port: 7272
  external_host: 192.0.2.50
features:
  ssl_enabled: true
security:
  network:
    mode: auto
"""

_LOCALHOST_CONFIG = """\
version: "3.0.0"
services:
  api:
    port: 7272
  external_host: localhost
features:
  ssl_enabled: false
security:
  network:
    mode: localhost
"""

_STALE_ENV = """\
GILJO_PUBLIC_URL=http://localhost:7272
VITE_API_URL=http://localhost:7272
VITE_WS_URL=ws://localhost:7272
DEFAULT_TENANT_KEY=tk_keepme
"""


_PATCHED_ENV_KEYS = ("GILJO_PUBLIC_URL", "VITE_API_URL", "VITE_WS_URL")


def _own_patched_env(monkeypatch):
    for key in _PATCHED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class TestStartupEnvSelfHeal:
    def test_lan_https_reconciles_stale_urls(self, tmp_path, monkeypatch):
        (tmp_path / "config.yaml").write_text(_LAN_CONFIG, encoding="utf-8")
        env_file = tmp_path / ".env"
        env_file.write_text(_STALE_ENV, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        _own_patched_env(monkeypatch)

        startup._patch_env_from_config()
        env = _parse_env(env_file)
        assert env["GILJO_PUBLIC_URL"] == "https://192.0.2.50:7272"
        assert env["VITE_API_URL"] == ""
        assert env["VITE_WS_URL"] == ""
        assert env["DEFAULT_TENANT_KEY"] == "tk_keepme"
        assert os.environ["VITE_API_URL"] == ""
        assert os.environ["GILJO_PUBLIC_URL"] == "https://192.0.2.50:7272"

    def test_localhost_install_is_untouched(self, tmp_path, monkeypatch):
        (tmp_path / "config.yaml").write_text(_LOCALHOST_CONFIG, encoding="utf-8")
        env_file = tmp_path / ".env"
        original = (
            "GILJO_PUBLIC_URL=http://localhost:7272\n"
            "VITE_API_URL=http://localhost:7272\n"
            "VITE_WS_URL=ws://localhost:7272\n"
        )
        env_file.write_text(original, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        _own_patched_env(monkeypatch)

        startup._patch_env_from_config()
        assert env_file.read_text(encoding="utf-8") == original

    def test_no_config_yaml_is_noop(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("GILJO_PUBLIC_URL=http://localhost:7272\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        startup._patch_env_from_config()
        assert env_file.read_text(encoding="utf-8") == "GILJO_PUBLIC_URL=http://localhost:7272\n"
