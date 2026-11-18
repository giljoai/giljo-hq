# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging

import pytest

from api import run_api


@pytest.fixture
def config_file(monkeypatch, tmp_path):
    path = tmp_path / "config.yaml"
    monkeypatch.setattr("giljo_mcp._config_io.get_config_path", lambda: path)
    return path


def test_missing_config_binds_loopback(config_file):
    assert not config_file.exists()

    assert run_api.get_default_host() == "127.0.0.1"


@pytest.mark.parametrize("damage", ["invalid_yaml", "not_a_file"])
def test_unreadable_config_binds_loopback(config_file, damage):
    if damage == "invalid_yaml":
        config_file.write_text("services: [unclosed\n", encoding="utf-8")
    else:
        config_file.mkdir()

    assert run_api.get_default_host() == "127.0.0.1"


@pytest.mark.parametrize("content", ["installation:\n  version: 2.0.0\n", "services:\n  api:\n    port: 7272\n", ""])
def test_present_config_without_the_host_key_keeps_todays_bind_and_says_which_key_to_set(config_file, caplog, content):
    config_file.write_text(content, encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        host = run_api.get_default_host()

    assert host == "0.0.0.0"
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "services.api.host" in warnings[0]


@pytest.mark.parametrize("host", ["0.0.0.0", "127.0.0.1", "198.51.100.20"])
def test_installer_written_host_is_honoured(config_file, host):
    config_file.write_text(f"services:\n  api:\n    host: {host}\n", encoding="utf-8")

    assert run_api.get_default_host() == host
