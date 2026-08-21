# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Regression: startup self-heal reconciles stale LAN network URLs in .env.

INF-6039 follow-up. The installer writes .env once, BEFORE HTTPS is configured,
so on a LAN/WAN box GILJO_PUBLIC_URL can persist as http:// and (on pre-fix
installs upgraded via git pull) VITE_API_URL/VITE_WS_URL can persist as absolute
localhost URLs. config.yaml is authoritative (rewritten after HTTPS setup).
_patch_env_from_config() runs on every startup BEFORE the frontend rebuild and
must reconcile both the missing and the present-but-wrong cases — and be a strict
no-op for localhost installs (and when config.yaml is absent, e.g. SaaS/Railway).
"""

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


# The keys `_patch_env_from_config` writes into os.environ. The code under test
# mutates the real process environment, so each test must hand those keys to
# monkeypatch first: `delenv(raising=False)` records the pre-test state and
# restores it at teardown, undoing writes made by PRODUCTION code, not just by the
# test. That replaces a hand-rolled save/try/finally/restore helper — which is
# exactly what monkeypatch is, minus the guarantee that teardown runs even when an
# assertion raises before the `finally` is reached (INF-9432).
#
# Removing the keys for the duration is inert here rather than merely convenient:
# `_patch_env_from_config` branches only on config.yaml, the .env file's existence,
# and the resolved external host — it never READS these variables to decide what to
# write (startup.py:668-710).
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
        # Agent-facing URL gets the real LAN host + https scheme.
        assert env["GILJO_PUBLIC_URL"] == "https://192.0.2.50:7272"
        # Frontend URLs emptied -> resolver uses same-origin window.location.origin.
        assert env["VITE_API_URL"] == ""
        assert env["VITE_WS_URL"] == ""
        # Unrelated keys are preserved.
        assert env["DEFAULT_TENANT_KEY"] == "tk_keepme"
        # os.environ is updated in-process so the imminent rebuild bakes the fix.
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
        # Localhost installs are already correct; nothing should change.
        assert env_file.read_text(encoding="utf-8") == original

    def test_no_config_yaml_is_noop(self, tmp_path, monkeypatch):
        # SaaS/Railway has no installer-written config.yaml and never calls this,
        # but guard anyway: absent config.yaml must not crash or rewrite .env.
        env_file = tmp_path / ".env"
        env_file.write_text("GILJO_PUBLIC_URL=http://localhost:7272\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        startup._patch_env_from_config()
        assert env_file.read_text(encoding="utf-8") == "GILJO_PUBLIC_URL=http://localhost:7272\n"
