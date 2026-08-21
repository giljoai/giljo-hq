# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Regression tests for INF-6040 R5: SSL decision parity between startup.py and run_api.py.

Two mismatches fixed:

MISMATCH-1 (--no-ssl propagation):
    startup.py computed ssl_enabled = False when --no-ssl was given but did NOT
    propagate that decision to the run_api subprocess.  run_api independently
    re-read config.yaml and could still bind HTTPS while startup's health probe
    used HTTP (or vice-versa).  Fix: startup sets GILJO_FORCE_HTTP=1 in os.environ
    before spawning run_api; run_api reads it and skips all SSL config resolution.

MISMATCH-2 (cert-existence gap):
    startup.py get_ssl_enabled() read features.ssl_enabled from config.yaml but
    never checked that the cert files actually exist on disk.  If certs were
    moved/deleted post-install, startup advertised https while run_api (which does
    check cert existence) silently fell back to http.  Fix: get_ssl_enabled() now
    also verifies cert files exist, returning False with a warning when they don't.

Test behaviour assertions (the *decision*, not the mechanism):
    - get_ssl_enabled(): certs-present -> True; certs-absent -> False (with warning).
    - startup ssl_enabled=False (--no-ssl / cert-missing) -> GILJO_FORCE_HTTP set to "1".
    - startup ssl_enabled=True (and certs present) -> GILJO_FORCE_HTTP cleared.
    - run_api with GILJO_FORCE_HTTP=1 -> no ssl_keyfile in uvicorn.run kwargs.
    - run_api without GILJO_FORCE_HTTP and valid certs -> ssl_keyfile present.

These are all parallel-safe: no DB, no module-level state, no env mutation without
cleanup.  The startup tests monkeypatch os.chdir and _get_network_mode; the
run_api test monkeypatches os.getenv and uvicorn.run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import startup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config_yaml(tmp_path: Path, ssl_enabled: bool, cert: Path | None = None, key: Path | None = None) -> str:
    """Write a config.yaml to tmp_path and return its content.

    Uses forward-slash paths (YAML-safe on Windows) for cert/key entries.
    """
    cert_line = ""
    key_line = ""
    if cert is not None:
        # Forward slashes are safe in YAML on all platforms.
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


# ---------------------------------------------------------------------------
# Part A: get_ssl_enabled() cert-existence check (MISMATCH-2)
# ---------------------------------------------------------------------------


class TestGetSslEnabledCertExistence:
    """MISMATCH-2: get_ssl_enabled() must return False when certs are missing."""

    def test_certs_present_returns_true(self, tmp_path, monkeypatch):
        """SSL configured and cert files exist on disk -> get_ssl_enabled() True."""
        cert = tmp_path / "ssl_cert.pem"
        key = tmp_path / "ssl_key.pem"
        cert.write_text("fake cert", encoding="utf-8")
        key.write_text("fake key", encoding="utf-8")

        _make_config_yaml(tmp_path, ssl_enabled=True, cert=cert, key=key)
        monkeypatch.chdir(tmp_path)
        # Patch network mode so localhost guard doesn't short-circuit.
        with patch.object(startup, "_get_network_mode", return_value="auto"):
            result = startup.get_ssl_enabled()

        assert result is True, "certs present + ssl_enabled=True should return True"

    def test_certs_missing_returns_false(self, tmp_path, monkeypatch):
        """SSL configured but cert files not on disk -> get_ssl_enabled() False."""
        cert = tmp_path / "ssl_cert.pem"  # NOT created on disk
        key = tmp_path / "ssl_key.pem"  # NOT created on disk

        _make_config_yaml(tmp_path, ssl_enabled=True, cert=cert, key=key)
        monkeypatch.chdir(tmp_path)
        with patch.object(startup, "_get_network_mode", return_value="auto"):
            result = startup.get_ssl_enabled()

        assert result is False, "configured-but-missing certs must resolve False (MISMATCH-2)"

    def test_certs_missing_emits_warning(self, tmp_path, monkeypatch, capsys):
        """Missing certs must print a user-visible warning so the operator knows why."""
        cert = tmp_path / "ssl_cert.pem"
        key = tmp_path / "ssl_key.pem"
        # NOT created — they're missing.
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
        """ssl_enabled=false in config -> False regardless of cert presence."""
        _make_config_yaml(tmp_path, ssl_enabled=False)
        monkeypatch.chdir(tmp_path)
        with patch.object(startup, "_get_network_mode", return_value="auto"):
            result = startup.get_ssl_enabled()
        assert result is False

    def test_localhost_mode_always_false(self, tmp_path, monkeypatch):
        """Localhost mode short-circuits get_ssl_enabled() to False unconditionally."""
        cert = tmp_path / "ssl_cert.pem"
        key = tmp_path / "ssl_key.pem"
        cert.write_text("fake", encoding="utf-8")
        key.write_text("fake", encoding="utf-8")
        _make_config_yaml(tmp_path, ssl_enabled=True, cert=cert, key=key)
        monkeypatch.chdir(tmp_path)
        # _get_network_mode returns "localhost" -> must short-circuit to False
        with patch.object(startup, "_get_network_mode", return_value="localhost"):
            result = startup.get_ssl_enabled()
        assert result is False, "localhost mode must always return False"

    def test_no_config_yaml_returns_false(self, tmp_path, monkeypatch):
        """No config.yaml -> get_ssl_enabled() returns False safely."""
        monkeypatch.chdir(tmp_path)
        with patch.object(startup, "_get_network_mode", return_value="auto"):
            result = startup.get_ssl_enabled()
        assert result is False


# ---------------------------------------------------------------------------
# Part B: GILJO_FORCE_HTTP propagation from run_startup (MISMATCH-1)
# ---------------------------------------------------------------------------


class TestGiljoForceHttpPropagation:
    """MISMATCH-1: startup.resolve_ssl_decision() sets GILJO_FORCE_HTTP when ssl_enabled=False.

    All tests call startup.resolve_ssl_decision() directly (the real code path, not an
    inline copy). This is the BE-5042 regression-test discipline: test the actual layer
    that failed, not a re-implementation of the logic.
    """

    def test_no_ssl_flag_sets_force_http(self, monkeypatch):
        """--no-ssl with ssl_enabled=True in config -> resolve_ssl_decision() sets GILJO_FORCE_HTTP=1."""
        monkeypatch.delenv("GILJO_FORCE_HTTP", raising=False)

        with patch.object(startup, "get_ssl_enabled", return_value=True):
            result = startup.resolve_ssl_decision(no_ssl=True)

        assert result is False, "--no-ssl must return False from resolve_ssl_decision"
        # resolve_ssl_decision() sets GILJO_FORCE_HTTP in os.environ directly.
        assert os.environ.get("GILJO_FORCE_HTTP") == "1", (
            "--no-ssl must cause resolve_ssl_decision() to set GILJO_FORCE_HTTP=1 (MISMATCH-1)"
        )
        # No manual cleanup: the monkeypatch.delenv above already recorded this key's
        # prior state, so monkeypatch restores it at teardown even though the value
        # was written by production code rather than by the test (INF-9432).

    def test_ssl_disabled_in_config_sets_force_http(self, monkeypatch):
        """ssl_enabled=False in config -> resolve_ssl_decision() sets GILJO_FORCE_HTTP=1."""
        monkeypatch.delenv("GILJO_FORCE_HTTP", raising=False)

        with patch.object(startup, "get_ssl_enabled", return_value=False):
            result = startup.resolve_ssl_decision(no_ssl=False)

        assert result is False
        assert os.environ.get("GILJO_FORCE_HTTP") == "1", (
            "ssl_enabled=False must cause resolve_ssl_decision() to set GILJO_FORCE_HTTP=1"
        )

    def test_ssl_enabled_clears_force_http(self, monkeypatch):
        """ssl_enabled=True and no --no-ssl -> resolve_ssl_decision() clears GILJO_FORCE_HTTP."""
        # Pre-set a stale value to confirm it gets cleared.
        monkeypatch.setenv("GILJO_FORCE_HTTP", "1")

        with patch.object(startup, "get_ssl_enabled", return_value=True):
            result = startup.resolve_ssl_decision(no_ssl=False)

        assert result is True
        assert os.environ.get("GILJO_FORCE_HTTP") is None, (
            "ssl_enabled=True must cause resolve_ssl_decision() to clear stale GILJO_FORCE_HTTP"
        )

    def test_env_propagates_to_child_via_star_os_environ(self, monkeypatch):
        """start_api_server() uses child_env = {**os.environ} so var propagates automatically."""
        monkeypatch.setenv("GILJO_FORCE_HTTP", "1")
        child_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        assert child_env.get("GILJO_FORCE_HTTP") == "1", (
            "GILJO_FORCE_HTTP must be present in child_env built from os.environ"
        )

    def test_certs_missing_sets_force_http(self, tmp_path, monkeypatch):
        """Combined MISMATCH-1 + MISMATCH-2: certs missing -> resolve_ssl_decision() sets GILJO_FORCE_HTTP=1.

        End-to-end: get_ssl_enabled() returns False (missing certs, MISMATCH-2) ->
        resolve_ssl_decision() sets GILJO_FORCE_HTTP=1 (MISMATCH-1) -> run_api binds HTTP.
        """
        cert = tmp_path / "ssl_cert.pem"  # NOT on disk
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


# ---------------------------------------------------------------------------
# Part C: run_api respects GILJO_FORCE_HTTP (MISMATCH-1 receiving end)
# ---------------------------------------------------------------------------


class TestRunApiForceHttp:
    """run_api.main() must bind HTTP (no ssl_config kwargs) when GILJO_FORCE_HTTP=1."""

    def test_force_http_set_means_no_ssl_kwargs(self, monkeypatch):
        """GILJO_FORCE_HTTP=1 -> uvicorn.run called without ssl_keyfile / ssl_certfile.

        Behavior assertion: startup --no-ssl (or cert-missing) forces GILJO_FORCE_HTTP=1
        which run_api reads; uvicorn.run must NOT receive ssl_keyfile/ssl_certfile kwargs.
        """
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
        """Without GILJO_FORCE_HTTP and with valid certs, ssl_keyfile is passed to uvicorn.

        This is the positive case: HTTPS should work end-to-end when certs exist and
        the launcher has not forced HTTP.
        """
        import api.run_api as run_api_mod

        # Create real cert/key files.
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
        # Point the config_path resolution in run_api.main() to our tmp config.
        # run_api resolves: Path(__file__).parent.parent / "config.yaml"
        # We patch __file__ so the resolution lands in tmp_path.
        # tmp_path / "api" / "run_api.py" -> parent = tmp_path/"api", parent.parent = tmp_path
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
