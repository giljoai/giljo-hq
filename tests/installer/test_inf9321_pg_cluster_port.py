# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-9321 — the installer assumed port 5432 and then hid the error that proved it wrong.

Measured on a fresh Ubuntu 24.04 guest running ``install.sh --yes`` as root.
PGDG postgres-18 installed fine, but ``pg_createcluster`` found 5432 already
occupied and put the new cluster on **5433**::

    pg_lsclusters -> 18  main  5433  online  postgres  /var/lib/postgresql/18/main

Two independent defects then compounded:

1. The port was never detected
   --------------------------
   ``install.py`` seeds ``settings["pg_port"] = 5432`` as a hardcoded default and
   nothing ever asks the machine what port the cluster actually listens on. Every
   downstream consumer reads that one setting -- the DatabaseInstaller connection,
   the generated ``.env`` ``DATABASE_URL``, ``config.yaml`` -- so all of them
   pointed at a port our cluster was not on. Worse, the pre-flight
   ``check_postgresql_connection`` is a bare TCP connect, so a *foreign* Postgres
   occupying 5432 satisfies it and the run proceeds with false confidence.

   Anyone with something already on 5432 (a host Postgres, a second WSL distro, a
   Docker publish) hits this on a fresh install, not just the lab guest.

2. The error that would have named it was discarded
   ------------------------------------------------
   ``DatabaseInstaller.setup()`` rebinds ``result`` to ``fallback_setup()`` when
   direct creation fails, dropping ``create_database_direct()``'s error list on the
   floor. The transcript showed only the generic "run the script manually" banner
   -- which an unattended run cannot act on -- and the real connection error
   appeared nowhere. Diagnosing a one-line port mismatch cost a re-run plus guest
   forensics.

Both checks below are written to fail against the pre-fix code: the first because
no detection existed, the second because the underlying error text was gone by the
time the caller printed anything.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from installer.core.config import ConfigManager  # noqa: E402
from installer.core.database import DatabaseInstaller  # noqa: E402
from installer.shared import postgres as pg_shared  # noqa: E402


# Verbatim shape of `pg_lsclusters --no-header` on the guest that failed:
# Ver Cluster Port Status Owner Data-directory Log-file
LSCLUSTERS_5433 = (
    "18  main  5433  online  postgres  /var/lib/postgresql/18/main  /var/log/postgresql/postgresql-18-main.log\n"
)

# The ordinary machine: our cluster IS on the default port. Detection must be a
# no-op here, or the fix would churn every healthy install.
LSCLUSTERS_5432 = (
    "18  main  5432  online  postgres  /var/lib/postgresql/18/main  /var/log/postgresql/postgresql-18-main.log\n"
)

# Two clusters, ours (highest version) bumped off the default port by the older one.
LSCLUSTERS_TWO = (
    "16  main  5432  online  postgres  /var/lib/postgresql/16/main  "
    "/var/log/postgresql/postgresql-16-main.log\n"
    "18  main  5433  online  postgres  /var/lib/postgresql/18/main  "
    "/var/log/postgresql/postgresql-18-main.log\n"
)


def _fake_probes(
    monkeypatch: pytest.MonkeyPatch,
    lsclusters_output: str,
    psql_port: int | None = None,
) -> list:
    """Stand in for both probes; raise on anything unexpected.

    Deliberately does NOT stub `detect_cluster_port` itself: an unrecognised
    command raises rather than silently passing, so a rewrite that shells out to
    something new has to come back through this test. Returns the recorded
    command list so a test can assert which probes actually ran.
    """
    calls: list = []

    def _run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append(cmd)
        if cmd[0] == "pg_lsclusters":
            return subprocess.CompletedProcess(cmd, 0, stdout=lsclusters_output, stderr="")
        if "psql" in cmd:
            if psql_port is None:
                return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="could not connect")
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{psql_port}\n", stderr="")
        raise AssertionError(f"unexpected probe command: {cmd}")

    monkeypatch.setattr(pg_shared.subprocess, "run", _run)
    monkeypatch.setattr(pg_shared.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(pg_shared.platform, "system", lambda: "Linux")
    return calls


def _fake_lsclusters(monkeypatch: pytest.MonkeyPatch, output: str) -> list:
    """`_fake_probes` with the psql fallback unavailable (the Debian/PGDG path)."""
    return _fake_probes(monkeypatch, output)


class TestClusterPortIsDetected:
    """The port the cluster actually listens on must reach every consumer."""

    def test_lsclusters_reporting_5433_is_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The live evidence, replayed: cluster on 5433 while 5432 looks occupied."""
        _fake_lsclusters(monkeypatch, LSCLUSTERS_5433)

        assert pg_shared.detect_cluster_port(current_port=5432) == 5433

    def test_default_port_is_left_alone_when_the_cluster_is_on_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No behaviour change on a normal machine -- the healthy path stays healthy."""
        _fake_lsclusters(monkeypatch, LSCLUSTERS_5432)

        assert pg_shared.detect_cluster_port(current_port=5432) == 5432

    def test_highest_version_online_cluster_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With an old cluster squatting on 5432, pick the one we just installed."""
        _fake_lsclusters(monkeypatch, LSCLUSTERS_TWO)

        assert pg_shared.detect_cluster_port(current_port=5432) == 5433

    def test_offline_clusters_are_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A `down` cluster is not somewhere we can create a database."""
        calls = _fake_lsclusters(
            monkeypatch,
            "18  main  5433  down  postgres  /var/lib/postgresql/18/main  \n",
        )

        assert pg_shared.detect_cluster_port(current_port=5432) is None
        # It must have tried the second probe rather than stopping at the first.
        assert any("psql" in cmd for cmd in calls), f"psql fallback never ran: {calls}"

    def test_psql_probe_answers_when_lsclusters_finds_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-Debian Linux, and the macOS/Homebrew analogue, come from this probe."""
        _fake_probes(monkeypatch, lsclusters_output="", psql_port=5433)

        assert pg_shared.detect_cluster_port(current_port=5432) == 5433

    def test_nothing_detected_leaves_the_caller_alone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No probe available -> None, so the installer keeps its configured port."""
        monkeypatch.setattr(pg_shared.platform, "system", lambda: "Linux")
        monkeypatch.setattr(pg_shared.shutil, "which", lambda name: None)

        assert pg_shared.detect_cluster_port(current_port=5432) is None

    def test_windows_does_not_probe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Windows detection is deliberately not built (see INF-9321 Lane C report).

        Guard it so nobody half-wires it: on Windows the probe must return None
        rather than shelling out to a Debian-only tool.
        """

        def _explode(*args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("no subprocess probe may run on Windows")

        monkeypatch.setattr(pg_shared.platform, "system", lambda: "Windows")
        monkeypatch.setattr(pg_shared.subprocess, "run", _explode)

        assert pg_shared.detect_cluster_port(current_port=5432) is None


class TestDetectedPortReachesTheConsumers:
    """Detection is worthless unless the number lands where connections are made."""

    def test_installer_settings_pick_up_the_detected_port(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """install.py must rewrite settings['pg_port'] -- the single source every step reads."""
        import install as install_module

        _fake_lsclusters(monkeypatch, LSCLUSTERS_5433)

        installer = install_module.UnifiedInstaller(settings={"install_dir": str(tmp_path)})
        assert installer.settings["pg_port"] == 5432, "precondition: the hardcoded default"

        installer.detect_postgresql_port()

        assert installer.settings["pg_port"] == 5433

    def test_run_detects_the_port_before_writing_any_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Wiring check: a detector nobody calls would fix nothing.

        Driven through ``run()`` with ``--setup-only`` on purpose -- that path
        skips discovery but still regenerates .env/config.yaml, so it is exactly
        where a wrong port would get re-stamped onto a repaired install.
        """
        import install as install_module

        _fake_lsclusters(monkeypatch, LSCLUSTERS_5433)

        installer = install_module.UnifiedInstaller(
            settings={"install_dir": str(tmp_path), "setup_only": True, "headless": True}
        )
        monkeypatch.setattr(installer, "welcome_screen", lambda: None)

        seen: dict[str, object] = {}

        def _stop_at_config():  # noqa: ANN202
            seen["pg_port"] = installer.settings.get("pg_port")
            return {"success": False, "errors": ["stopped by test"]}

        monkeypatch.setattr(installer, "generate_configs", _stop_at_config)

        installer.run()

        assert seen.get("pg_port") == 5433, (
            "config generation ran before the port was detected (or detection is not wired in)"
        )

    def test_database_installer_connects_on_the_detected_port(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The DB-creation connection params must carry 5433, not the assumed 5432."""
        import install as install_module
        from installer.core import database as database_module

        _fake_lsclusters(monkeypatch, LSCLUSTERS_5433)

        captured: dict[str, object] = {}

        class _CapturingInstaller:
            def __init__(self, settings):  # noqa: ANN001
                captured.update(settings)

            def setup(self):  # noqa: ANN201
                # Stop the phase here -- we only care what port it was handed.
                return {"success": False, "errors": ["stopped by test"]}

        monkeypatch.setattr(database_module, "DatabaseInstaller", _CapturingInstaller)

        installer = install_module.UnifiedInstaller(settings={"install_dir": str(tmp_path)})
        installer.detect_postgresql_port()
        installer.setup_database()

        assert captured.get("port") == 5433

    def test_generated_config_and_env_carry_the_detected_port(self, tmp_path: Path) -> None:
        """config.yaml and .env are what the app reads on every later boot."""
        manager = ConfigManager(
            settings={
                "install_dir": str(tmp_path),
                "pg_host": "localhost",
                "pg_port": 5433,
                "db_name": "giljo_mcp",
                "owner_password": "ownerpw",  # noqa: S106 - test fixture, not a credential
                "user_password": "userpw",  # noqa: S106 - test fixture, not a credential
            }
        )

        assert manager.generate_config_yaml()["success"] is True
        parsed = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        assert parsed["database"]["port"] == 5433

        assert manager.generate_env_file()["success"] is True
        env_text = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "@localhost:5433/giljo_mcp" in env_text
        assert "DB_PORT=5433" in env_text

    def test_success_banner_prints_the_detected_port_not_5432(self) -> None:
        """Audit catch: the final 'Installation Complete' banner is the one line
        a user acts on right after install. A hardcoded 5432 there recreates the
        assume-5432 bug in the last remaining consumer -- the user runs
        psql -p 5432 against the wrong (or no) server, right after being told
        the install worked."""
        source = (REPO_ROOT / "install.py").read_text(encoding="utf-8")
        assert "@ localhost:5432 (owner:" not in source, (
            "the success banner hardcodes 5432 instead of reading settings['pg_port']"
        )
        assert "@ localhost:{db_port} (owner:" in source, (
            "the success banner must print the DETECTED port from settings['pg_port']"
        )


class TestWindowsPreChecksThePort:
    """install.ps1 pins --serverport 5432; say so before installing, not after.

    Port DETECTION is deliberately not built for Windows (no pg_lsclusters, and
    the EDB build wants a scram password the installer does not hold yet). The
    Windows half of INF-9321 is therefore a pre-check: refuse in words rather
    than let the EDB installer fail behind a numeric winget exit code, minutes
    later, after the user has already typed a password.
    """

    @staticmethod
    def _install_ps1() -> str:
        path = REPO_ROOT / "scripts" / "install.ps1"
        assert path.exists(), "scripts/install.ps1 is preserved into the CE export; absence is a rename"
        return path.read_text(encoding="utf-8")

    def test_helper_exists(self) -> None:
        assert "function Test-PortInUse" in self._install_ps1()

    def test_port_is_checked_before_the_pinned_serverport_install(self) -> None:
        source = self._install_ps1()

        check = source.find("Test-PortInUse -Port 5432")
        # Anchor on the invocation itself, not on the "--serverport 5432" string:
        # that string also appears in prose above, and matching it would compare
        # against a comment instead of the command.
        install = source.find('Start-Process -FilePath "winget"')

        assert check != -1, "the winget PostgreSQL block does not pre-check port 5432"
        assert install != -1, "expected the PostgreSQL install to run winget via Start-Process"
        assert "--serverport 5432" in source, "expected the winget override to pin --serverport 5432"
        assert check < install, "the port check must run BEFORE the install, not after"

    def test_the_refusal_names_the_port_and_what_to_do(self) -> None:
        """A number alone is not a diagnosis -- that is the whole point of INF-9321."""
        source = self._install_ps1()
        block_start = source.find("Test-PortInUse -Port 5432")
        message = source[block_start : block_start + 800]

        assert "5432" in message
        assert "already in use" in message
        assert "re-run this script" in message


class TestTheRealErrorSurvivesTheFallback:
    """An unattended run cannot follow a 'do it by hand' banner. It needs the reason."""

    @staticmethod
    def _installer() -> DatabaseInstaller:
        return DatabaseInstaller(
            settings={
                "host": "localhost",
                "port": 5432,
                "username": "postgres",
                "password": "irrelevant",  # noqa: S106 - test fixture, not a credential
                "db_name": "giljo_mcp",
                "unattended": True,
            }
        )

    def test_direct_creation_error_reaches_the_caller(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """setup() used to rebind `result` to fallback_setup() and drop these errors."""
        installer = self._installer()
        real_error = "Cannot connect to PostgreSQL server at localhost:5432"

        monkeypatch.setattr("installer.core.database.check_postgresql_connection", lambda *a, **k: True)
        monkeypatch.setattr(
            installer, "detect_postgresql_version", lambda: {"success": True, "version": 18, "version_string": "18.0"}
        )
        monkeypatch.setattr(installer, "create_database_direct", lambda: {"success": False, "errors": [real_error]})
        monkeypatch.setattr(
            installer,
            "fallback_setup",
            lambda: {
                "success": False,
                "manual_step_required": True,
                "errors": ["Database was not created. Run the generated script manually, then re-run the installer."],
            },
        )

        result = installer.setup()

        assert result["success"] is False
        joined = " | ".join(result.get("errors", []))
        assert real_error in joined, (
            "the underlying connection error was swallowed -- the transcript shows only "
            f"the generic fallback banner: {joined!r}"
        )

    def test_connection_failure_names_the_host_and_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A port mismatch must be one readable line, not a forensics exercise."""
        psycopg2 = pytest.importorskip("psycopg2")

        installer = self._installer()
        installer.port = 5432

        def _refuse(*args, **kwargs):  # noqa: ANN002, ANN003
            raise psycopg2.OperationalError("could not connect to server: Connection refused")

        monkeypatch.setattr("installer.core.database.psycopg2.connect", _refuse)

        result = installer.create_database_direct()

        assert result["success"] is False
        joined = " | ".join(result.get("errors", []))
        assert "5432" in joined, f"the error text does not say which port was tried: {joined!r}"
        assert "localhost" in joined
