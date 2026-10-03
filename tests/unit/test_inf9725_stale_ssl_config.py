# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import sys

import pytest

import api.run_api as run_api_mod


def _write_stale_config(tmp_path, with_cert_files: bool = True) -> None:
    cert = tmp_path / "ssl_cert.pem"
    key = tmp_path / "ssl_key.pem"
    if with_cert_files:
        cert.write_text("fake cert", encoding="utf-8")
        key.write_text("fake key", encoding="utf-8")
    (tmp_path / "config.yaml").write_text(
        'version: "3.0.0"\n'
        "features:\n"
        "  ssl_enabled: true\n"
        "paths:\n"
        f"  ssl_cert: {str(cert).replace(chr(92), '/')!r}\n"
        f"  ssl_key: {str(key).replace(chr(92), '/')!r}\n",
        encoding="utf-8",
    )


def _run_main(monkeypatch, tmp_path) -> dict:
    captured: dict = {}

    def fake_run(app, **kwargs):
        captured.update(kwargs)

    monkeypatch.delenv("GILJO_FORCE_HTTP", raising=False)
    monkeypatch.setattr(run_api_mod, "uvicorn", type("_FakeUvicorn", (), {"run": staticmethod(fake_run)})())
    monkeypatch.setattr(run_api_mod, "__file__", str(tmp_path / "api" / "run_api.py"))
    monkeypatch.setattr(sys, "argv", ["run_api.py", "--port", "19874"])
    run_api_mod.main()
    return captured


@pytest.mark.parametrize("with_cert_files", [True, False])
def test_stale_ssl_enabled_starts_on_plain_http(monkeypatch, tmp_path, with_cert_files):
    _write_stale_config(tmp_path, with_cert_files=with_cert_files)

    kwargs = _run_main(monkeypatch, tmp_path)

    assert kwargs, "uvicorn.run must have been called"
    assert "ssl_keyfile" not in kwargs
    assert "ssl_certfile" not in kwargs


def test_stale_ssl_keys_log_one_info_line_pointing_at_the_guide(monkeypatch, tmp_path, caplog):
    _write_stale_config(tmp_path)

    with caplog.at_level(logging.INFO, logger="api.run_api"):
        run_api_mod._note_ignored_ssl_settings(tmp_path / "config.yaml")

    lines = [r for r in caplog.records if "Built-in HTTPS was removed" in r.getMessage()]
    assert len(lines) == 1
    assert lines[0].levelno == logging.INFO
    assert "user guide" in lines[0].getMessage()


def test_clean_config_logs_nothing_and_missing_config_is_fine(tmp_path, caplog):
    (tmp_path / "config.yaml").write_text("features:\n  ssl_enabled: false\n", encoding="utf-8")

    with caplog.at_level(logging.INFO, logger="api.run_api"):
        assert run_api_mod._note_ignored_ssl_settings(tmp_path / "config.yaml") is False
        assert run_api_mod._note_ignored_ssl_settings(tmp_path / "absent.yaml") is False

    assert not caplog.records
