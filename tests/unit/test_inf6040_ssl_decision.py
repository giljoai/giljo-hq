# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import startup




def _make_config_yaml(tmp_path: Path, ssl_enabled: bool, cert: Path | None = None, key: Path | None = None) -> str:
    cert_line = ""
    key_line = ""
    if cert is not None:
        cert_line = f"  ssl_cert: {str(cert).replace(chr(92), '/')!r}"
        key_line = f"  ssl_key: {str(key).replace(chr(92), '/')!r}"

    paths_section = ""
    if cert_line:
        paths_section = f"paths:\n{cert_line}\n{key_line}\n"

    content = (
        'version: "3.0.0"\n'
        "deployment_context: lan\n"
        "features:\n"
        f"  ssl_enabled: {'true' if ssl_enabled else 'false'}\n"
        "security:\n"
        "  network:\n"
        "    mode: auto\n" + paths_section
    )
    (tmp_path / "config.yaml").write_text(content, encoding="utf-8")
    return content




class TestGetSslEnabledCertExistence:

    def test_certs_present_returns_true(self, tmp_path, monkeypatch):
        cert = tmp_path / "ssl_cert.pem"
        key = tmp_path / "ssl_key.pem"
        cert.write_text("fake cert", encoding="utf-8")
        key.write_text("fake key", encoding="utf-8")

        _make_config_yaml(tmp_path, ssl_enabled=True, cert=cert, key=key)
        monkeypatch.chdir(tmp_path)
        with patch.object(startup, "_get_network_mode", return_value="auto"):
            result = startup.get_ssl_enabled()

        assert result is True, "certs present + ssl_enabled=True should return True"

    def test_certs_missing_returns_false(self, tmp_path, monkeypatch):
        cert = tmp_path / "ssl_cert.pem"
        key = tmp_path / "ssl_key.pem"

        _make_config_yaml(tmp_path, ssl_enabled=True, cert=cert, key=key)
        monkeypatch.chdir(tmp_path)
        with patch.object(startup, "_get_network_mode", return_value="auto"):
            result = startup.get_ssl_enabled()

        assert result is False, "configured-but-missing certs must resolve False (MISMATCH-2)"

    def test_certs_missing_emits_warning(self, tmp_path, monkeypatch, capsys):
        cert = tmp_path / "ssl_cert.pem"
        key = tmp_path / "ssl_key.pem"
        _make_config_yaml(tmp_path, ssl_enabled=True, cert=cert, key=key)
        monkeypatch.chdir(tmp_path)
        with patch.object(startup, "_get_network_mode", return_value="auto"):
            startup.get_ssl_enabled()

        out, err = capsys.readouterr()
        combined = (out + err).lower()
        assert "cert" in combined, (
            f"get_ssl_enabled() must warn operator when certs are missing — got stdout={out!r} stderr={err!r}"
        )

    def test_ssl_false_in_config_returns_false(self, tmp_path, monkeypatch):
        _make_config_yaml(tmp_path, ssl_enabled=False)
        monkeypatch.chdir(tmp_path)
        with patch.object(startup, "_get_network_mode", return_value="auto"):
            result = startup.get_ssl_enabled()
        assert result is False

    def test_localhost_mode_always_false(self, tmp_path, monkeypatch):
        cert = tmp_path / "ssl_cert.pem"
        key = tmp_path / "ssl_key.pem"
        cert.write_text("fake", encoding="utf-8")
        key.write_text("fake", encoding="utf-8")
        _make_config_yaml(tmp_path, ssl_enabled=True, cert=cert, key=key)
        monkeypatch.chdir(tmp_path)
        with patch.object(startup, "_get_network_mode", return_value="localhost"):
            result = startup.get_ssl_enabled()
        assert result is False, "localhost mode must always return False"

    def test_no_config_yaml_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch.object(startup, "_get_network_mode", return_value="auto"):
            result = startup.get_ssl_enabled()
        assert result is False




class TestGiljoForceHttpPropagation:

    def test_no_ssl_flag_sets_force_http(self, monkeypatch):
        monkeypatch.delenv("GILJO_FORCE_HTTP", raising=False)

        with patch.object(startup, "get_ssl_enabled", return_value=True):
            result = startup.resolve_ssl_decision(no_ssl=True)

        assert result is False, "--no-ssl must return False from resolve_ssl_decision"
        assert os.environ.get("GILJO_FORCE_HTTP") == "1", (
            "--no-ssl must cause resolve_ssl_decision() to set GILJO_FORCE_HTTP=1 (MISMATCH-1)"
        )

    def test_ssl_disabled_in_config_sets_force_http(self, monkeypatch):
        monkeypatch.delenv("GILJO_FORCE_HTTP", raising=False)

        with patch.object(startup, "get_ssl_enabled", return_value=False):
            result = startup.resolve_ssl_decision(no_ssl=False)

        assert result is False
        assert os.environ.get("GILJO_FORCE_HTTP") == "1", (
            "ssl_enabled=False must cause resolve_ssl_decision() to set GILJO_FORCE_HTTP=1"
        )

    def test_ssl_enabled_clears_force_http(self, monkeypatch):
        monkeypatch.setenv("GILJO_FORCE_HTTP", "1")

        with patch.object(startup, "get_ssl_enabled", return_value=True):
            result = startup.resolve_ssl_decision(no_ssl=False)

        assert result is True
        assert os.environ.get("GILJO_FORCE_HTTP") is None, (
            "ssl_enabled=True must cause resolve_ssl_decision() to clear stale GILJO_FORCE_HTTP"
        )

    def test_env_propagates_to_child_via_star_os_environ(self, monkeypatch):
        monkeypatch.setenv("GILJO_FORCE_HTTP", "1")
        child_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        assert child_env.get("GILJO_FORCE_HTTP") == "1", (
            "GILJO_FORCE_HTTP must be present in child_env built from os.environ"
        )

    def test_certs_missing_sets_force_http(self, tmp_path, monkeypatch):
        cert = tmp_path / "ssl_cert.pem"
        key = tmp_path / "ssl_key.pem"
        _make_config_yaml(tmp_path, ssl_enabled=True, cert=cert, key=key)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("GILJO_FORCE_HTTP", raising=False)

        with patch.object(startup, "_get_network_mode", return_value="auto"):
            result = startup.resolve_ssl_decision(no_ssl=False)

        assert result is False, "missing certs -> resolve_ssl_decision() must return False"
        assert os.environ.get("GILJO_FORCE_HTTP") == "1", (
            "missing certs -> ssl_enabled=False -> GILJO_FORCE_HTTP must be set"
        )




class TestRunApiForceHttp:

    def test_force_http_set_means_no_ssl_kwargs(self, monkeypatch):
        import api.run_api as run_api_mod

        captured_kwargs: list[dict] = []

        def fake_uvicorn_run(app, **kwargs):
            captured_kwargs.append(kwargs)

        monkeypatch.setenv("GILJO_FORCE_HTTP", "1")
        monkeypatch.setattr(run_api_mod, "uvicorn", type("_FakeUvicorn", (), {"run": staticmethod(fake_uvicorn_run)})())

        old_argv = sys.argv[:]
        try:
            sys.argv = ["run_api.py", "--port", "19872"]
            run_api_mod.main()
        except SystemExit:
            pass
        finally:
            sys.argv = old_argv

        assert captured_kwargs, "uvicorn.run must have been called"
        kwargs = captured_kwargs[0]
        assert "ssl_keyfile" not in kwargs, (
            "GILJO_FORCE_HTTP=1 must result in no ssl_keyfile in uvicorn.run kwargs (MISMATCH-1)"
        )
        assert "ssl_certfile" not in kwargs, "GILJO_FORCE_HTTP=1 must result in no ssl_certfile in uvicorn.run kwargs"

    def test_without_force_http_and_valid_certs_ssl_config_present(self, monkeypatch, tmp_path):
        import api.run_api as run_api_mod

        cert = tmp_path / "ssl_cert.pem"
        key = tmp_path / "ssl_key.pem"
        cert.write_text("fake cert", encoding="utf-8")
        key.write_text("fake key", encoding="utf-8")

        cfg = (
            'version: "3.0.0"\n'
            "deployment_context: lan\n"
            "features:\n"
            "  ssl_enabled: true\n"
            f"paths:\n"
            f"  ssl_cert: {str(cert).replace(chr(92), '/')!r}\n"
            f"  ssl_key: {str(key).replace(chr(92), '/')!r}\n"
        )
        config_path = tmp_path / "config.yaml"
        config_path.write_text(cfg, encoding="utf-8")

        captured_kwargs: list[dict] = []

        def fake_uvicorn_run(app, **kwargs):
            captured_kwargs.append(kwargs)

        monkeypatch.delenv("GILJO_FORCE_HTTP", raising=False)
        monkeypatch.setattr(run_api_mod, "uvicorn", type("_FakeUvicorn", (), {"run": staticmethod(fake_uvicorn_run)})())
        monkeypatch.setattr(run_api_mod, "__file__", str(tmp_path / "api" / "run_api.py"))

        old_argv = sys.argv[:]
        try:
            sys.argv = ["run_api.py", "--port", "19873"]
            run_api_mod.main()
        except SystemExit:
            pass
        finally:
            sys.argv = old_argv

        assert captured_kwargs, "uvicorn.run must have been called"
        kwargs = captured_kwargs[0]
        assert "ssl_keyfile" in kwargs, (
            "valid certs + no GILJO_FORCE_HTTP must pass ssl_keyfile to uvicorn (MISMATCH-1 check)"
        )
        assert "ssl_certfile" in kwargs
